"""`vine init` / init_forest: bootstrap an empty, valid, servable forest."""

import subprocess
from pathlib import Path

import pytest

from monkeyllm import Vine
from monkeyllm.errors import E_SCHEMA, VineError
from monkeyllm.forest import Forest, init_forest
from monkeyllm.lint import lint_forest
from monkeyllm.server import ForestPool


class TestInitForest:
    def test_creates_valid_forest_with_clean_git(self, tmp_path):
        info = init_forest(tmp_path / "nova", title="Floresta Nova")
        root = Path(info["root"])
        assert info["commit"]

        errors = [i for i in lint_forest(Forest(root)) if i.level == "error"]
        assert errors == []

        out = subprocess.run(["git", "-C", str(root), "ls-files"],
                             capture_output=True, text=True, check=True)
        assert set(out.stdout.split()) == {".gitignore", "_index.md", "_meta/schema.md"}

    def test_immediately_plantable_and_locatable(self, tmp_path):
        init_forest(tmp_path / "nova", title="Floresta Nova")
        vine = Vine(tmp_path / "nova", writable=True)
        try:
            r = vine.plant({
                "id": "first-banana",
                "type": "note",
                "title": "First banana",
                "summary": "First note planted right after init, proving the forest "
                           "is born ready for writes and search.",
                "parent": "_index",
                "body": "# First banana\n\n## Content\n\nHello, forest.",
                "source": "agent",
            })
            assert r["commit"]
            hits = vine.locate("first banana")
            assert any(x["id"] == "first-banana" for x in hits["results"])
        finally:
            vine.close()

    def test_refuses_existing_forest(self, tmp_path):
        init_forest(tmp_path / "nova", title="Floresta Nova")
        with pytest.raises(VineError) as e:
            init_forest(tmp_path / "nova", title="Outra")
        assert e.value.code == E_SCHEMA

    def test_registry_sees_new_forest_without_restart(self, tmp_path):
        pool = ForestPool(root=tmp_path, writable=False)
        try:
            assert pool.list()["forests"] == []
            init_forest(tmp_path / "nova", title="Floresta Nova")
            assert [f["id"] for f in pool.list()["forests"]] == ["nova"]
            assert pool.get("nova").look("_index")["title"] == "Floresta Nova"
        finally:
            pool.close()
