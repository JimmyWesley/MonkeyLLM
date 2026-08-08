"""Policy and ScopedVine — the single enforcement seam (spec J.3).

Every Station surface reaches a forest through `ScopedVine` and nothing
else, so an unscoped `Vine` handle is unreachable by construction (J.1).
The seam exists from the first commit precisely because retrofitting a
security boundary is how bypasses are born.

Phase A (T07) ships **full-forest policies only**. Prefix scoping — the
`allow`/`deny` subtree grants of J.3 and the two oracle invariants it must
satisfy — lands with T08 together with its leak suite. Until then a
prefix-restricted policy is REFUSED at construction rather than accepted
and under-enforced: for a security boundary the safe failure mode is a
loud one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from monkeyllm.errors import VineError

# Host-level code: the node is visible, the action is not permitted. Distinct
# from J.3's out-of-scope rule, which MUST report E_NOT_FOUND instead (an
# authorization error there would itself be an existence oracle).
E_FORBIDDEN = "E_FORBIDDEN"

CAPS = frozenset({"read", "write", "query", "tend", "ingest", "admin"})

WHOLE_FOREST = ("",)


@dataclass(frozen=True)
class Policy:
    """What one principal may do on one forest."""

    forest: str
    caps: frozenset[str] = field(default_factory=lambda: frozenset({"read"}))
    allow: tuple[str, ...] = WHOLE_FOREST
    deny: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        unknown = set(self.caps) - CAPS
        if unknown:
            raise ValueError(f"unknown capabilities: {sorted(unknown)}")
        if tuple(self.allow) != WHOLE_FOREST or self.deny:
            raise NotImplementedError(
                "prefix-scoped policies are not enforced yet (spec J.3 / task "
                "T08). Refusing to store a policy the Station cannot honour."
            )

    def grants(self, cap: str) -> bool:
        return "admin" in self.caps or cap in self.caps

    @classmethod
    def full(cls, forest: str) -> Policy:
        return cls(forest=forest, caps=frozenset(CAPS))


# primitive -> capability required to call it
REQUIRED_CAP = {
    "locate": "read",
    "look": "read",
    "move": "read",
    "pick": "read",
    "scan": "read",
    "sniff": "read",
    "harvest": "read",
    "query": "query",
    "tend": "tend",
    "plant": "write",
    "graft": "write",
}


class ScopedVine:
    """A Vine seen through one principal's policy."""

    def __init__(self, vine, policy: Policy):
        self._vine = vine
        self.policy = policy

    def call(self, primitive: str, /, **kwargs) -> dict:
        """Invoke a primitive under the policy. Returns the primitive's dict
        or the spec error envelope — never raises for expected failures."""
        cap = REQUIRED_CAP.get(primitive)
        if cap is None:
            return VineError(
                "E_SCHEMA", f"unknown primitive: {primitive}"
            ).to_dict()
        if not self.policy.grants(cap):
            return VineError(
                E_FORBIDDEN,
                f"'{primitive}' requires the '{cap}' capability",
                hint=f"This principal holds: {sorted(self.policy.caps)}.",
            ).to_dict()
        try:
            if primitive == "harvest":
                from monkeyllm.harvest import harvest

                return harvest(self._vine, **kwargs)
            return getattr(self._vine, primitive)(**kwargs)
        except VineError as e:
            return e.to_dict()
        except TypeError as e:  # bad/missing arguments from an API client
            return VineError("E_SCHEMA", str(e)).to_dict()
