# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""L.2 — sources, resolution and trust.

Four doors, one resolver, and one rule that decides the shape of everything
after it: **the source resolves to an immutable artifact before anything is
validated**. A tag can be force-pushed and a branch moves nightly, so the
thing that was signed has to be the thing that runs — which means a git ref
is resolved to a commit SHA and the SHA is what the record holds.

The three tiers are not a ranking of quality. They say what is *known*:
`verified` came from an index this deployment trusts, `signed` carries a tag
signature that checks against the keys the forge publishes for its author,
and `unverified` is everything else. A tracked branch is `unverified` by
construction — a branch has no tag, so there is nothing to verify.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from monkeyllm.errors import E_SCHEMA, VineError

E_EXT_INSTALL = "E_EXT_INSTALL"

TIER_VERIFIED = "verified"
TIER_SIGNED = "signed"
TIER_UNVERIFIED = "unverified"

_GIT_RE = re.compile(
    r"^(?:git\+)?(?:(?P<scheme>https?|ssh)://)?"
    r"(?P<host>[a-z0-9.-]+\.[a-z]{2,})/(?P<path>[^@#]+?)(?:\.git)?"
    r"(?:[@#](?P<ref>[^@#]+))?$", re.I)
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_ARCHIVE_RE = re.compile(r"^https?://", re.I)
_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,39}$")

# L.2 rule 4: identity is delegated to the forge, so the forge is where the
# keys are read. Adding one is adding a line here, never a plugin — the
# whole point is that this list is short and auditable.
FORGE_KEYS = {
    "github.com": "https://api.github.com/users/{owner}/gpg_keys",
    "gitlab.com": "https://gitlab.com/api/v4/users?username={owner}",
}


@dataclass
class Resolved:
    """An immutable artifact plus everything known about where it came from."""

    root: Path                       # the extracted/checked-out tree
    source: str                      # what the operator typed
    kind: str                        # index | git | archive | file
    tier: str = TIER_UNVERIFIED
    revision: str | None = None      # the commit SHA, when there is one
    tracking: str | None = None      # the moving ref, when there is one
    identity: dict | None = None     # account + key fingerprint that verified
    reason: str | None = None        # why the tier is not higher
    cleanup: Path | None = field(default=None, repr=False)

    def record(self) -> dict:
        out = {"source": self.source, "kind": self.kind, "tier": self.tier}
        for key in ("revision", "tracking", "identity", "reason"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out


def _local_git(source: str) -> tuple[Path, str | None] | None:
    """A path to a git repository, with an optional `@ref`.

    Development and air-gapped installs both need it, and it is the same
    question the remote form asks — so it takes the same road rather than a
    second one that could disagree with it.
    """
    for candidate, ref in ((source, None), *(
            (source.rsplit(sep, 1)[0], source.rsplit(sep, 1)[1])
            for sep in ("@", "#") if sep in source)):
        path = Path(candidate).expanduser()
        if (path / ".git").exists() or (path / "HEAD").exists():
            return path, ref
    return None


def classify(source: str) -> str:
    """Which door the operator used. Order matters: a local path that also
    looks like an id is a path, because the filesystem is checkable and an
    index entry is a claim."""
    if _local_git(source):
        return "git"
    if Path(source).expanduser().exists():
        return "file"
    if _ARCHIVE_RE.match(source) and source.lower().endswith(".zip"):
        return "archive"
    if _GIT_RE.match(source):
        return "git"
    if _ID_RE.match(source):
        return "index"
    raise VineError(E_SCHEMA, f"unrecognised extension source: {source!r}",
                    hint="an index id, a git URL, an https .zip, or a path")


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------

def _git(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(("git",) + args, cwd=cwd, capture_output=True,
                          text=True)
    if proc.returncode != 0:
        raise VineError(E_EXT_INSTALL, "git failed",
                        hint=(proc.stderr or proc.stdout).strip()[:400],
                        data={"reason": "git"})
    return proc.stdout


def _parse_git(source: str) -> tuple[str, str, str, str | None]:
    local = _local_git(source)
    if local:
        path, ref = local
        # No forge, so no published keys and no `signed` tier — which is
        # the truth about a local clone rather than a limitation.
        return "", path.name, str(path), ref
    m = _GIT_RE.match(source)
    if not m:
        raise VineError(E_SCHEMA, f"not a git source: {source!r}")
    host = m.group("host").lower()
    path = m.group("path").strip("/")
    url = f"https://{host}/{path}.git"
    return host, path, url, m.group("ref")


def resolve_git(source: str, workdir: Path,
                verify: bool = True) -> Resolved:
    host, path, url, ref = _parse_git(source)
    dest = workdir / "checkout"
    _git("clone", "--quiet", url, str(dest))

    # L.2 rule 1: whatever the operator named, the record holds the SHA.
    target = ref or _default_branch(dest)
    _git("checkout", "--quiet", target, cwd=dest)
    revision = _git("rev-parse", "HEAD", cwd=dest).strip()

    tracking = None
    if not ref or not _is_immutable(dest, ref):
        # L.2 rule 2: a moving ref installs and is MARKED. An author must
        # not have to cut a release per test.
        tracking = target

    out = Resolved(root=dest, source=source, kind="git",
                   revision=revision, tracking=tracking, cleanup=workdir)

    if tracking:
        # A branch carries no tag, so there is nothing to verify. The tier
        # says it without needing a rule of its own.
        out.reason = f"tracking a moving ref ({tracking}); nothing to verify"
        return out
    if not verify:
        out.reason = "signature verification not requested"
        return out

    if not host:
        out.reason = "a local repository publishes no keys to verify against"
        return out
    owner = path.split("/")[0]
    _verify_tag(out, dest, ref, host, owner)
    return out


def _default_branch(repo: Path) -> str:
    try:
        head = _git("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD",
                    cwd=repo).strip()
        return head.rsplit("/", 1)[-1] or "HEAD"
    except VineError:
        return "HEAD"


def _is_immutable(repo: Path, ref: str) -> bool:
    """A SHA is immutable; a tag is treated as one because L.2 rule 1 pins
    what it resolved to. A branch is not."""
    if _SHA_RE.match(ref):
        return True
    try:
        _git("show-ref", "--verify", "--quiet", f"refs/tags/{ref}", cwd=repo)
        return True
    except VineError:
        return False


def fetch_forge_keys(host: str, owner: str) -> list[str]:
    """L.2 rule 4 — the forge publishes its users' public keys.

    Split out so a test can substitute it: reaching the network to decide a
    tier is exactly the kind of thing a suite must be able to stub.
    """
    template = FORGE_KEYS.get(host)
    if not template:
        raise VineError(E_EXT_INSTALL, f"no key service known for {host}",
                        data={"reason": "forge"})
    url = template.format(owner=owner)
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "User-Agent": "monkeyllm"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    keys = []
    for entry in payload if isinstance(payload, list) else []:
        raw = entry.get("raw_key") or entry.get("key")
        if raw:
            keys.append(raw)
    return keys


def _verify_tag(out: Resolved, repo: Path, ref: str, host: str,
                owner: str) -> None:
    """Verify the tag's signature against the forge's published keys.

    Every failure degrades the tier and says why; none of them raises. An
    unsigned extension is installable (L.9 rule 4 — the operator decides),
    and a host with no gpg is a host that cannot know, which is not the same
    as a bad signature.
    """
    if not shutil.which("gpg"):
        out.reason = "gpg is not available, so a signature cannot be checked"
        return
    try:
        keys = fetch_forge_keys(host, owner)
    except Exception as exc:
        out.reason = f"could not read {host} keys for {owner}: {exc}"
        return
    if not keys:
        out.reason = f"{owner} publishes no signing keys on {host}"
        return

    with tempfile.TemporaryDirectory() as home:
        env = dict(os.environ, GNUPGHOME=home)
        fingerprints = []
        for key in keys:
            proc = subprocess.run(["gpg", "--batch", "--import"],
                                  input=key, text=True, capture_output=True,
                                  env=env)
            fingerprints += re.findall(r"key ([0-9A-F]{8,}):", proc.stderr)
        proc = subprocess.run(["git", "verify-tag", "--raw", ref],
                              cwd=repo, capture_output=True, text=True,
                              env=env)
        if proc.returncode != 0:
            out.reason = "the tag carries no valid signature from that account"
            return
        out.tier = TIER_SIGNED
        out.identity = {"forge": host, "account": owner,
                        "keys": sorted(set(fingerprints))[:8]}


# ---------------------------------------------------------------------------
# archives and local files
# ---------------------------------------------------------------------------

def _extract(archive: Path, workdir: Path) -> Path:
    dest = workdir / "tree"
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for member in zf.namelist():
            # J.13.2's rule, applied here: members are checked BEFORE
            # anything is written, and the archive is refused rather than
            # a member skipped.
            if member.startswith("/") or ".." in Path(member).parts \
                    or "\\" in member:
                raise VineError(E_EXT_INSTALL,
                                f"archive member escapes its root: {member!r}",
                                data={"reason": "archive"})
        zf.extractall(dest)
    # A zip that carries one top-level directory is that directory.
    entries = [p for p in dest.iterdir() if not p.name.startswith("__MACOSX")]
    if len(entries) == 1 and entries[0].is_dir() \
            and not (dest / "manifest.json").exists():
        return entries[0]
    return dest


def resolve_archive(source: str, workdir: Path) -> Resolved:
    local = workdir / "download.zip"
    with urllib.request.urlopen(source, timeout=60) as resp:
        local.write_bytes(resp.read())
    return Resolved(root=_extract(local, workdir), source=source,
                    kind="archive", cleanup=workdir,
                    reason="an archive carries no forge identity")


def resolve_file(source: str, workdir: Path) -> Resolved:
    path = Path(source).expanduser().resolve()
    if path.is_dir():
        return Resolved(root=path, source=source, kind="file",
                        reason="a local directory carries no signature")
    return Resolved(root=_extract(path, workdir), source=source, kind="file",
                    cleanup=workdir,
                    reason="a local archive carries no forge identity")


# ---------------------------------------------------------------------------
# the curated index
# ---------------------------------------------------------------------------

DEFAULT_INDEX = os.environ.get(
    "MONKEYLLM_EXT_INDEX",
    "https://raw.githubusercontent.com/JimmyWesley/MonkeyLLM/main/"
    "extensions/index.json")


def read_index(url: str | None = None) -> dict:
    url = url or DEFAULT_INDEX
    if Path(url).exists():
        return json.loads(Path(url).read_text(encoding="utf-8"))
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def resolve_index(ext_id: str, workdir: Path,
                  index: dict | None = None) -> Resolved:
    """L.0: the index carries signed POINTERS, never artifacts. Resolving an
    id is therefore resolving whatever source the entry names, and the tier
    rises to `verified` only when the identity the index expects is the
    identity that actually verified."""
    data = index if index is not None else read_index()
    entry = (data.get("extensions") or {}).get(ext_id)
    if not entry:
        raise VineError(E_EXT_INSTALL, f"no extension named {ext_id!r} in the "
                                       f"index", data={"reason": "index"})
    out = resolve(entry["source"], workdir)
    out.kind = "index"
    expected = entry.get("identity")
    if expected and out.identity and \
            out.identity.get("account") == expected.get("account"):
        out.tier = TIER_VERIFIED
        out.reason = None
    elif expected:
        out.reason = (f"the index expects {expected.get('account')} and the "
                      f"artifact did not verify as them")
    return out


def resolve(source: str, workdir: Path, *, index: dict | None = None,
            verify: bool = True) -> Resolved:
    """The one door. Everything downstream sees a `Resolved`, never a URL."""
    kind = classify(source)
    if kind == "git":
        return resolve_git(source, workdir, verify=verify)
    if kind == "archive":
        return resolve_archive(source, workdir)
    if kind == "file":
        return resolve_file(source, workdir)
    return resolve_index(source, workdir, index=index)
