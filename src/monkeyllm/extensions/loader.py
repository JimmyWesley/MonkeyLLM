# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""L.4 / L.10 — activation, and what happens to what this host cannot serve.

Two rules carry this module:

**An extension does not act at import time.** It is activated by exactly one
call, `register(api)`, and every claim is made inside it. An extension that
can register later is an extension whose surface nobody can enumerate.

**A contribution the host cannot serve is inert and named, never an error**
(L.10, which is J.1.2 rule 4 applied to extensions). The loader parses and
validates a panel even where nothing renders it — so a broken panel is
caught on the author's machine rather than in a Station — and then reports
it unserved instead of failing or pretending.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from monkeyllm.errors import E_NOT_FOUND, E_SCHEMA, VineError
from monkeyllm.extensions.api import Claim, ExtensionAPI, ModelAccess, Registry
from monkeyllm.extensions.manifest import Manifest, parse_manifest
from monkeyllm.extensions.worker import Worker, interpreter_for

E_EXT_LOAD = "E_EXT_LOAD"


@dataclass
class Loaded:
    manifest: Manifest
    api: ExtensionAPI
    unserved: list[str] = field(default_factory=list)
    panel: dict | None = None


@dataclass
class LoadReport:
    """What a host got, what it could not serve, and what refused to load.

    `failed` never raises out of `load_all`: one broken extension must not
    stop the others, which is `discover_converters`' own standing rule.
    """

    registry: Registry
    loaded: list[Loaded] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    unserved: list[dict] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "loaded": [l.manifest.id for l in self.loaded],
            "failed": self.failed,
            "unserved": self.unserved,
            "roles": self.registry.roles(),
            "attributions": self.registry.attributions(),
        }


def read_manifest(tree: Path) -> Manifest:
    path = Path(tree) / "manifest.json"
    if not path.exists():
        raise VineError(E_NOT_FOUND, "manifest.json is missing",
                        hint=f"looked in {tree}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VineError(E_SCHEMA, f"manifest.json is not valid JSON: {exc}")
    return parse_manifest(raw)


def _module_name(tree: Path, module: str, ext_id: str) -> str:
    """One name per (installed tree, module).

    The tree digest is in the name because a process may hold two installs
    of the same id — a test builds several hosts, and an operator's staging
    copy is not their live one. Without it the second load would silently
    take over the first one's name.
    """
    digest = hashlib.sha256(str(Path(tree).resolve())
                            .encode("utf-8")).hexdigest()[:8]
    return (f"monkeyllm_ext_{ext_id.replace('-', '_')}_"
            f"{module.replace('.', '_')}_{digest}")


def _import_module(tree: Path, module: str, ext_id: str,
                   extra_paths: tuple[str, ...] = ()) -> Any:
    path = Path(tree) / (module.replace(".", "/") + ".py")
    if not path.exists():
        raise VineError(E_EXT_LOAD, f"{ext_id}: module {module!r} is missing",
                        hint=f"expected {path.name} at the package root")
    name = _module_name(tree, module, ext_id)
    # Imported ONCE per load. The loader touches an extension's module twice
    # — for `register` and again for each declared handler — and executing
    # it twice gave the extension two module objects: `register()` wrote to
    # one and its handlers read from the other, so any module-level state an
    # author keeps (a client, a cache, a counter) silently split in half.
    # Nothing raised, which is what made it worth a comment.
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    added = [p for p in extra_paths if p not in sys.path]
    sys.path[:0] = added
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    except Exception as exc:
        sys.modules.pop(name, None)
        raise VineError(E_EXT_LOAD, f"{ext_id}: {module} failed to import",
                        hint=f"{type(exc).__name__}: {exc}") from None
    finally:
        for p in added:
            try:
                sys.path.remove(p)
            except ValueError:
                pass


def _resolve_handler(tree: Path, ext_id: str, ref: str,
                     extra_paths: tuple[str, ...]) -> Callable:
    module, _, func = ref.partition(":")
    if not func:
        raise VineError(E_SCHEMA, f"{ext_id}: handler {ref!r} is not "
                                  f"module:function")
    mod = _import_module(tree, module, ext_id, extra_paths)
    target = getattr(mod, func, None)
    if not callable(target):
        raise VineError(E_EXT_LOAD,
                        f"{ext_id}: {ref} is not a callable")
    return target


def _site_packages(venv: Path) -> tuple[str, ...]:
    globs = list(venv.glob("lib/python*/site-packages")) + \
        list(venv.glob("Lib/site-packages"))
    return tuple(str(p) for p in globs if p.exists())


def load(tree: Path, *, registry: Registry, config: dict | None = None,
         vine: Any = None, complete: Callable | None = None,
         bound_roles: dict | None = None, meter: Callable | None = None,
         models_factory: Callable | None = None,
         config_provider: Callable | None = None,
         venv: Path | None = None, host_surfaces: set[str] | None = None,
         log: Any = None) -> Loaded:
    """Activate one extension. Raises; `load_all` is what contains failures.

    `host_surfaces` is how a host says what it can serve — a CLI passes no
    `panel`, a Station passes it. Absent, everything is assumed servable,
    because a host that does not say is a host that is not choosing.
    """
    tree = Path(tree)
    manifest = read_manifest(tree)
    extra = _site_packages(venv) if venv else ()

    # L.6: a required role with no binding refuses BEFORE anything loads.
    bound = dict(bound_roles or {})
    missing = [r for r in manifest.models.requires if r not in bound]
    if missing:
        raise VineError(
            E_EXT_LOAD,
            f"{manifest.id}: required model role(s) not bound: "
            f"{', '.join(sorted(missing))}",
            hint="bind the role before installing, or the first call is where "
                 "the operator finds out",
            data={"reason": "roles", "roles": sorted(missing)})

    for spec in manifest.models.registers:
        registry.register_role(manifest.id, spec.role, spec.kind)
        bound.setdefault(spec.role, {"kind": spec.kind})

    # `models_factory` lets a host build the access object per extension —
    # which it must, because metering, quota and the audit row all name the
    # extension, and a single shared caller could not say which one spent.
    models = (models_factory(manifest.id, bound) if models_factory
              else ModelAccess(manifest.id, complete, bound, meter))
    api = ExtensionAPI(
        manifest, registry, config=config, vine=vine, log=log, models=models,
        config_provider=config_provider)

    entry = _import_module(tree, manifest.entry, manifest.id, extra)
    register = getattr(entry, "register", None)
    if not callable(register):
        raise VineError(E_EXT_LOAD,
                        f"{manifest.id}: {manifest.entry}.py defines no "
                        f"register(api)")
    register(api)
    api.seal()

    # Declared contributions the extension did not claim itself are wired
    # from the manifest, so a converter needs no boilerplate in register().
    _wire_manifest_claims(manifest, tree, registry, extra, venv, api)

    unserved, panel = _panel(manifest, tree, host_surfaces)
    return Loaded(manifest=manifest, api=api, unserved=unserved, panel=panel)


def _wire_manifest_claims(manifest: Manifest, tree: Path, registry: Registry,
                          extra: tuple[str, ...], venv: Path | None,
                          api: ExtensionAPI) -> None:
    already = {(c.seam, c.spec.get("name") or c.spec.get("handler"))
               for c in registry.by_extension(manifest.id)}
    worker = Worker(manifest.id, tree, interpreter_for(venv or tree),
                    extra_paths=extra)
    for seam, spec in manifest.handlers():
        ref = spec.handler
        name = getattr(spec, "name", None) or ref
        if (seam, name) in already:
            continue
        if spec.heavy:
            # L.5: never imported into this interpreter.
            handler = _heavy(worker, ref)
        else:
            handler = _resolve_handler(tree, manifest.id, ref, extra)
        payload = {"name": name, "handler": ref, "heavy": spec.heavy}
        if seam == "converters":
            payload["extensions"] = set(spec.extensions)
        registry.add(Claim(ext_id=manifest.id, seam=seam, handler=handler,
                           spec=payload, heavy=spec.heavy))


def _heavy(worker: Worker, ref: str) -> Callable:
    def call(*args, **kwargs):
        return worker.call(ref, *args, **kwargs)
    call.__name__ = ref.replace(":", "_")
    call.heavy = True
    return call


def _panel(manifest: Manifest, tree: Path,
           host_surfaces: set[str] | None) -> tuple[list[str], dict | None]:
    """L.10 — validate it wherever we are, render it only where we can."""
    if not manifest.contributes.panel:
        return [], None
    path = Path(tree) / manifest.contributes.panel
    if not path.exists():
        raise VineError(E_SCHEMA,
                        f"{manifest.id}: panel {manifest.contributes.panel!r} "
                        f"is missing")
    try:
        panel = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VineError(E_SCHEMA,
                        f"{manifest.id}: panel is not valid JSON: {exc}")
    if not isinstance(panel, dict):
        raise VineError(E_SCHEMA, f"{manifest.id}: panel must be an object")
    if host_surfaces is not None and "panel" not in host_surfaces:
        return ["panel"], panel
    return [], panel


def load_all(installs, store, *, host_surfaces: set[str] | None = None,
             **kwargs) -> LoadReport:
    """Load many, and let no single failure stop the rest."""
    registry = kwargs.pop("registry", None) or Registry()
    report = LoadReport(registry=registry)
    for install in installs:
        provider = kwargs.pop("config_factory", None)
        try:
            got = load(store.tree(install.id), registry=registry,
                       config=store.read_config(install.id),
                       config_provider=(None if provider is None
                                        else provider(install.id)),
                       venv=store.venv(install.id),
                       host_surfaces=host_surfaces, **kwargs)
        except VineError as exc:
            registry.drop(install.id)
            report.failed.append({"id": install.id, "code": exc.code,
                                  "message": exc.message, "hint": exc.hint})
            continue
        except Exception as exc:  # never trust a third party to raise well
            registry.drop(install.id)
            report.failed.append({"id": install.id, "code": E_EXT_LOAD,
                                  "message": f"{type(exc).__name__}: {exc}"})
            continue
        report.loaded.append(got)
        for surface in got.unserved:
            report.unserved.append({"id": install.id, "surface": surface,
                                    "note": "declared (no host surface)"})
    return report
