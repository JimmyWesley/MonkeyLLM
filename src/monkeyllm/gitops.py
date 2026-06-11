"""Git-native writes: every plant/graft is a commit (architecture §2.6)."""

from __future__ import annotations

import subprocess
from pathlib import Path

GIT_IDENTITY = ["-c", "user.name=vine", "-c", "user.email=vine@monkeyllm.local"]


class GitRepo:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self.root), *GIT_IDENTITY, *args],
            capture_output=True,
            text=True,
            check=check,
        )

    @property
    def is_repo(self) -> bool:
        try:
            out = self._run("rev-parse", "--is-inside-work-tree", check=False)
            return out.returncode == 0 and out.stdout.strip() == "true"
        except FileNotFoundError:
            return False

    def init(self) -> None:
        self._run("init", "--quiet")

    def commit(self, paths: list[Path], message: str) -> str:
        """Stage paths and commit. Returns the commit sha."""
        rels = [str(p.resolve().relative_to(self.root.resolve())) for p in paths]
        self._run("add", "--", *rels)
        self._run("commit", "--quiet", "-m", message)
        return self._run("rev-parse", "HEAD").stdout.strip()

    def head(self) -> str | None:
        out = self._run("rev-parse", "HEAD", check=False)
        return out.stdout.strip() if out.returncode == 0 else None
