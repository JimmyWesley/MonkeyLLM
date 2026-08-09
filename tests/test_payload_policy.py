# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Spec A.3.1 (acceptance F.8): binaries never enter the forest git."""

import subprocess

import pytest

from monkeyllm.gitops import GitRepo


def git_ls_files(root) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files"], capture_output=True, text=True, check=True
    )
    return out.stdout.splitlines()


class TestForestGitHasNoBinaries:
    def test_fixture_tracks_no_db(self, forest_ro):
        tracked = git_ls_files(forest_ro)
        assert tracked, "fixture must have an embedded git repo"
        offenders = [f for f in tracked if f.endswith((".db", ".sqlite"))]
        assert offenders == [], f"binaries tracked by the forest git: {offenders}"

    def test_fixture_gitignore_excludes_binaries(self, forest_ro):
        ignore = (forest_ro / ".gitignore").read_text(encoding="utf-8")
        for pattern in ("_derived/", "*.db", "*.sqlite", "_assets/"):
            assert pattern in ignore, pattern

    def test_payload_still_on_disk(self, forest_ro):
        # out of git != out of the forest: the dataset payload must exist
        assert (forest_ro / "sales" / "report-q1-2026.db").is_file()


class TestGitopsHardGuard:
    @pytest.fixture()
    def repo(self, tmp_path):
        subprocess.run(["git", "-C", str(tmp_path), "init", "--quiet"], check=True)
        return GitRepo(tmp_path)

    def test_commit_stages_only_md(self, repo, tmp_path):
        md = tmp_path / "note.md"
        md.write_text("# hi\n", encoding="utf-8")
        db = tmp_path / "data.db"
        db.write_bytes(b"\x00binary")
        repo.commit([md, db], "plant(note): test")
        assert git_ls_files(tmp_path) == ["note.md"]

    def test_commit_refuses_binary_only(self, repo, tmp_path):
        db = tmp_path / "data.db"
        db.write_bytes(b"\x00binary")
        with pytest.raises(ValueError, match="A.3.1"):
            repo.commit([db], "attempted binary commit")
