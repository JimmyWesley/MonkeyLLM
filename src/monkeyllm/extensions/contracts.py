# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""L.3 — what each seam passes its handler, declared once.

Before this, the answer lived in the specification's prose and nowhere in
the code, so the conformance kit could say "it works" about an extension
whose handler took the wrong parameters. Python binds by name: a
misspelling is a `TypeError` at CALL time, which for a `curation` handler
is whatever hour the next ingest runs.

The declaration does three jobs that used to be three separate texts — the
kit checks a signature against it, the authoring reference (L.16) is
generated from it, and the host has one place to read when it decides what
to pass. Two descriptions of one contract agree only where somebody
compared them; here there is one.
"""

from __future__ import annotations

import inspect
import pathlib
from dataclasses import dataclass, field

from monkeyllm.errors import E_SCHEMA, VineError
from monkeyllm.extensions.manifest import SEAMS


# L.5 (v0.84): what a HEAVY handler is passed on top of its seam's own
# arguments. It is the same everywhere, because it is a property of the
# worker protocol and not of any one seam: the request carries the
# extension's resolved config beside the handler's arguments, and a handler
# that does not declare it never sees it.
#
# It lives in `names` — so the kit does not refuse `def convert(path,
# config)`, which is the shape `docs/extending.md` teaches — and it is
# rendered apart in the generated reference, because a LIGHT handler reads
# its settings through `api.config` and is passed nothing.
HEAVY_PARAMS: tuple[tuple[str, str], ...] = (
    ("config", "the extension's RESOLVED configuration: the manifest's "
               "declared defaults under the operator's stored values, read "
               "at call time so an edit in the console reaches the next "
               "call without a restart. Passed only to a `heavy: true` "
               "handler, and only when the handler declares it — a worker "
               "that does not ask receives exactly what it received "
               "before. A declared secret travels here and nowhere else: "
               "not a log, not a report, not an audit row, not a crash "
               "trace."),
)


@dataclass(frozen=True)
class SeamContract:
    """One seam's call shape.

    `params` are the names the host passes by keyword. A handler MAY omit
    any of them and MAY accept `**kwargs`; what it may not do is name a
    parameter this list does not contain, because that is the shape that
    binds to nothing and fails at call time.
    """

    seam: str
    summary: str
    params: tuple[tuple[str, str], ...]      # (name, what it carries)
    returns: str
    precedence: str
    positional: tuple[str, ...] = ()          # passed by position, in order

    @property
    def names(self) -> set[str]:
        return {n for n, _ in self.params} | set(self.positional)

    def names_for(self, heavy: bool) -> set[str]:
        """What this seam passes a handler of that weight.

        The split is real and not a courtesy: a LIGHT handler reads its
        settings through `api.config` in `register(api)` and is passed
        nothing, so one naming `config` without a default would bind to
        nothing and fail at call time — the exact silence this check exists
        to break. A heavy handler is across a pipe, where `api` does not
        reach, and the request carries it (L.5).
        """
        return self.names | ({n for n, _ in HEAVY_PARAMS} if heavy else set())

    def signature(self) -> str:
        """The shape an author writes, for the generated reference."""
        parts = list(self.positional) + [n for n, _ in self.params]
        return f"def handler({', '.join(parts)}, **kwargs)"


CONTRACTS: dict[str, SeamContract] = {
    c.seam: c for c in (
        SeamContract(
            seam="converters",
            summary="Turn a file this deployment could not read into a "
                    "document the forest can.",
            positional=("path",),
            params=(),
            returns="a dict: {kind: 'markdown'|'dataset'|'payload', title, "
                    "markdown, …}. A plain dict rather than the engine's "
                    "dataclass — an extension is coupled to the seam's "
                    "shape, never to the class behind it, and a heavy "
                    "handler answers across a pipe where only JSON travels.",
            precedence="operator command hooks > extensions by install "
                       "order > injected extras > entry points > built-ins",
        ),
        SeamContract(
            seam="curation",
            summary="Adjust a draft passport after the host's own hooks "
                    "have run.",
            positional=("draft",),
            params=(),
            returns="the draft, adjusted. Returning nothing leaves it "
                    "untouched.",
            precedence="all hooks run, in install order, AFTER the host's "
                       "own — an operator's approval hook (J.8.1) is the "
                       "last word on a draft",
        ),
        SeamContract(
            seam="events",
            summary="React to something that happened on a forest.",
            params=(
                ("event", "the event name, e.g. 'node.planted'"),
                ("forest", "the forest it happened on"),
                ("principal", "who caused it"),
                ("data", "what the act already knew — ids, counts, states"),
                ("metadata", "title/summary when the act carried them"),
            ),
            returns="nothing. A return value is ignored; a raise is "
                    "contained and logged (L.7 rule 5).",
            precedence="all handlers run; order unspecified",
        ),
        SeamContract(
            seam="jobs",
            summary="Maintenance an operator runs on demand, beside the "
                    "Ranger.",
            params=(("forest", "the forest to work on"),),
            returns="a dict describing what it did.",
            precedence="independent; pulled, never scheduled",
        ),
        SeamContract(
            seam="tools",
            summary="A tool the agents reaching this forest can call.",
            params=(),
            returns="a dict. Anything else is wrapped as {'result': …}.",
            precedence="namespaced; a name outside the extension's "
                       "namespace refuses the install",
        ),
        SeamContract(
            seam="routes",
            summary="An HTTP endpoint under /v1/ext/<id>/<name>.",
            params=(("forest", "the forest named in the request"),),
            returns="a dict, serialised as the JSON body.",
            precedence="namespaced by the path itself",
        ),
        SeamContract(
            seam="ranking",
            summary="Reorder the sweep's results before the budget cuts "
                    "them.",
            params=(
                ("query", "the question as asked"),
                ("results", "the candidates, in the order they arrived"),
            ),
            returns="a list drawn FROM `results`. It may reorder and drop; "
                    "anything returned that was not handed in is discarded "
                    "(G.4.2.1's rule about invented targets, applied to "
                    "ordering).",
            precedence="first claimant wins; named in the Part D trace",
        ),
        SeamContract(
            seam="prompt",
            summary="Add to the system prompt of an answer.",
            params=(
                ("mode", "'sweep' or 'walk'"),
                ("question", "the question as asked"),
                ("system", "the prompt as it stands"),
            ),
            returns="a string, APPENDED to the prompt. It is never a "
                    "replacement: the rules the product's answers depend on "
                    "— citation, the refusal to invent — cannot be removed "
                    "by an extension.",
            precedence="first claimant wins; named in the Part D trace",
        ),
        SeamContract(
            seam="roles",
            summary="Declared in the manifest, not implemented by a "
                    "handler.",
            params=(),
            returns="—",
            precedence="a collision refuses the install",
        ),
        SeamContract(
            seam="panel",
            summary="Declared in the manifest as a JSON file, not "
                    "implemented by a handler.",
            params=(),
            returns="—",
            precedence="one per extension",
        ),
    )
}

# L.3 / F.205: the catalogue and the contracts are one list read two ways.
_MISSING = set(SEAMS) - set(CONTRACTS)
_EXTRA = set(CONTRACTS) - set(SEAMS)
if _MISSING or _EXTRA:          # pragma: no cover - a defect, not a state
    raise RuntimeError(
        f"seam contracts disagree with the catalogue: missing {_MISSING}, "
        f"unknown {_EXTRA}")

# The two seams above that name no handler: declared in the manifest and
# implemented by nothing, so a signature check has nothing to check.
DECLARATIVE = frozenset({"roles", "panel"})


def check_signature(seam: str, handler, heavy: bool = False) -> str | None:
    """None when the handler fits its seam, else what is wrong with it.

    The rule is about DEFAULTS, not about `**kwargs`. A first cut treated
    `**kwargs` as an excuse for a misspelled parameter and was wrong in the
    exact case it was written for: given `def on_event(event, forrest,
    **rest)`, `**rest` absorbs the `forest` the host passes and `forrest`
    is still left unfilled — a `TypeError` at call time, which is the
    silence this check exists to break.

    So: a parameter the seam does not pass is fine **if it has a default**
    (it simply keeps it) and is a fault otherwise, whatever else the
    signature accepts.
    """
    contract = CONTRACTS.get(seam)
    if contract is None or seam in DECLARATIVE:
        return None
    try:
        sig = inspect.signature(handler)
    except (TypeError, ValueError):           # a builtin, a C callable
        return None

    accepts_varargs = any(p.kind is p.VAR_POSITIONAL
                          for p in sig.parameters.values())
    named = [p for p in sig.parameters.values()
             if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
    # Positional arguments are matched by POSITION, so the first N named
    # parameters answer for them whatever they are called.
    consumed = 0 if accepts_varargs else len(contract.positional)
    shape = [(p.name, p.default is not inspect.Parameter.empty)
             for p in named[consumed:]]
    return _mismatch(contract, seam, [p.name for p in named], shape,
                     accepts_varargs, heavy)


def _mismatch(contract, seam, all_names, shape, accepts_varargs,
              heavy: bool = False):
    """The one judgement, shared by the runtime and the source readers."""
    passes = contract.names_for(heavy)
    unfilled = [n for n, has_default in shape
                if not has_default and n not in passes]
    if unfilled:
        offered = ", ".join(sorted(passes)) or "(nothing)"
        return (f"names {', '.join(unfilled)}, which the {seam!r} seam does "
                f"not pass; it passes: {offered}")
    if not accepts_varargs and len(all_names) < len(contract.positional):
        return (f"takes {len(all_names)} parameter(s) and the {seam!r} seam "
                f"passes {len(contract.positional)} by position "
                f"({', '.join(contract.positional)})")
    return None


def signature_from_source(path, func: str):
    """The parameter shape of `func` in `path`, read WITHOUT importing it.

    Importing to inspect would execute the module — and a `heavy` handler's
    module imports the very dependency L.5 exists to keep out of this
    process, so the check that guards an author's mistake would defeat the
    rule that guards the deployment. It would also run third-party code at
    kit time, which L.2 rule 5 is careful to say the kit does not do.

    Returns `(shape, accepts_varargs)` where `shape` is
    `[(name, has_default), …]` in declaration order — or None when the
    function is not there, because an absent handler is already the kit's
    own separate check and naming one fault twice helps nobody.
    """
    import ast

    try:
        tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == func:
            a = node.args
            positional = list(a.posonlyargs) + list(a.args)
            # `defaults` fills the TAIL of the positional list; `kw_defaults`
            # is per keyword-only argument and carries None where there is
            # none.
            filled = len(a.defaults)
            shape = [(p.arg, i >= len(positional) - filled)
                     for i, p in enumerate(positional)]
            shape += [(p.arg, d is not None)
                      for p, d in zip(a.kwonlyargs, a.kw_defaults)]
            return shape, a.vararg is not None
    return None


def declares_config(path, func: str) -> bool:
    """L.5 rule 1 (v0.84): whether a heavy handler asked for its settings.

    Read off the SOURCE for `signature_from_source`'s reason — a heavy
    handler's module imports the very dependency L.5 exists to keep out of
    this process, so importing it here to look at a parameter list would
    defeat the rule the worker exists to serve.

    The question is asked on the host rather than in the child on purpose:
    a worker that did not ask must receive the request it received in
    v0.83, byte for byte, and a request carrying a `config` the child then
    discards is not that request. It is also the rule that keeps a declared
    secret out of a process that has no use for it.
    """
    found = signature_from_source(path, func)
    if found is None:
        return False
    shape, _ = found
    return any(name == "config" for name, _ in shape)


def check_source_signature(seam: str, path, func: str,
                           heavy: bool = False) -> str | None:
    """`check_signature`'s answer, read off the source instead of an object."""
    contract = CONTRACTS.get(seam)
    if contract is None or seam in DECLARATIVE:
        return None
    found = signature_from_source(path, func)
    if found is None:
        return None
    shape, accepts_varargs = found
    consumed = 0 if accepts_varargs else len(contract.positional)
    return _mismatch(contract, seam, [n for n, _ in shape], shape[consumed:],
                     accepts_varargs, heavy)


def require_signature(seam: str, handler, ext_id: str,
                      heavy: bool = False) -> None:
    problem = check_signature(seam, handler, heavy)
    if problem:
        raise VineError(
            E_SCHEMA, f"{ext_id}: the {seam} handler {problem}",
            hint=f"the shape is {CONTRACTS[seam].signature()}")
