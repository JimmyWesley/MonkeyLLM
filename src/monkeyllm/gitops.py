# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Git-native writes: every plant/graft is a commit (architecture §2.6)."""

from __future__ import annotations

import subprocess
from pathlib import Path

GIT_IDENTITY = ["-c", "user.name=vine", "-c", "user.email=vine@monkeyllm.local"]

# J.4/C.16 (v0.58): the standard attribution trailer. The engine never
# WRITES a value into it (the host decides who acted — the engine stays
# principal-blind), but the KEY is engine vocabulary so `history` can read
# it back as `by` without the host teaching it a spelling.
ATTRIBUTION_TRAILER = "station-principal"

# C.16: record separators for one-shot log parsing — unit separator between
# fields, record separator between commits, so a commit MESSAGE containing
# newlines cannot be mistaken for a boundary.
_FIELD_SEP = "\x1f"
_RECORD_SEP = "\x1e"


class GitRepo:
    def __init__(self, root: Path):
        self.root = Path(root)
        # J.4 (v0.57): lines the next commit appends after a blank line, in
        # git's trailer convention. A host attributing writes sets them
        # around the call (`Vine.commit_trailers`); the engine appends what
        # it is handed and never reads it — it stays principal-blind. Before
        # this seam the host amended the commit it had just been given:
        # two commits and a log read per write, on the one thread every
        # write already queues for.
        self.trailers: list[str] = []

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self.root), *GIT_IDENTITY, *args],
            capture_output=True,
            text=True,
            check=check,
        )

    @property
    def is_repo(self) -> bool:
        """True only when the forest root is ITSELF a repo top-level.

        `--is-inside-work-tree` would also say yes when the forest merely
        lives inside some OUTER repo — and then forest commits would land
        in that outer repo (the exact disaster the A.3/gitops design
        forbids). The forest must own its `.git`.
        """
        try:
            out = self._run("rev-parse", "--show-toplevel", check=False)
            return (out.returncode == 0
                    and Path(out.stdout.strip()).resolve() == self.root.resolve())
        except FileNotFoundError:
            return False

    def init(self) -> None:
        self._run("init", "--quiet")

    def commit(self, paths: list[Path], message: str) -> str:
        """Stage paths and commit. Returns the commit sha.

        Hard guard (spec A.3.1): only .md files are ever staged — binaries
        (dataset payloads, assets) are referenced by payload_hash, never
        versioned, so the forest repo cannot balloon with blobs.
        """
        rels = [
            str(p.resolve().relative_to(self.root.resolve()))
            for p in paths
            if p.suffix.lower() == ".md"
        ]
        if not rels:
            raise ValueError("nothing to commit: only .md files are versioned (spec A.3.1)")
        if self.trailers:
            message = message.rstrip() + "\n\n" + "\n".join(self.trailers)
        self._run("add", "--", *rels)
        self._run("commit", "--quiet", "-m", message)
        return self._run("rev-parse", "HEAD").stdout.strip()

    def file_history(self, rel_path: str, limit: int = 20) -> list[dict]:
        """C.16 (v0.58): one file's commits, newest first, through renames.

        Each entry: `commit`, `at` (ISO 8601 with time of day — the strict
        author date), `message` (the subject line), and `by` when the
        commit carries the attribution trailer. `--follow` keeps a
        transplanted document's past whole across its move (C.15 relies on
        git's rename detection for this).
        """
        out = self._run(
            "log", "--follow", f"-n{max(1, int(limit))}",
            f"--format=%H{_FIELD_SEP}%aI{_FIELD_SEP}%B{_RECORD_SEP}",
            "--", rel_path, check=False)
        entries: list[dict] = []
        if out.returncode != 0:
            return entries
        for record in out.stdout.split(_RECORD_SEP):
            record = record.strip("\n")
            if not record:
                continue
            sha, _, rest = record.partition(_FIELD_SEP)
            at, _, body = rest.partition(_FIELD_SEP)
            lines = body.splitlines()
            entry = {"commit": sha.strip(), "at": at.strip(),
                     "message": lines[0].strip() if lines else ""}
            for line in lines[1:]:
                if line.lower().startswith(f"{ATTRIBUTION_TRAILER}:"):
                    entry["by"] = line.split(":", 1)[1].strip()
            entries.append(entry)
        return entries

    def maintain(self) -> str:
        """H.8 (v0.57): ask git to tend the repo — `gc --auto`, git's own
        thresholds deciding. Touches `.git/` only: no history, no working
        tree, no catalog row. Returns 'ran' | 'unavailable'; best effort,
        because maintenance must never fail the work it maintains."""
        try:
            out = self._run("gc", "--auto", "--quiet", check=False)
            return "ran" if out.returncode == 0 else "unavailable"
        except (FileNotFoundError, OSError):
            return "unavailable"

    def head(self) -> str | None:
        out = self._run("rev-parse", "HEAD", check=False)
        return out.stdout.strip() if out.returncode == 0 else None
