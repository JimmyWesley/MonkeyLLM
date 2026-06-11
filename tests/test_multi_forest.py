"""Forest registry (spec C.0 / acceptance F.10): one server, N forests."""

import json
import os
import sys
from pathlib import Path

import anyio
import pytest

from monkeyllm.errors import E_NOT_FOUND, E_SCHEMA, VineError
from monkeyllm.server import ForestPool

from conftest import build_forest

REPO = Path(__file__).resolve().parents[1]

MARKER_NODE = """---
id: notas/marcador-amazonia
type: nota
title: Marcador exclusivo da amazonia
summary: Nó sentinela que só existe na floresta amazonia, usado para provar isolamento entre florestas.
created: '2026-06-11'
updated: '2026-06-11'
---

# Marcador exclusivo da amazonia

Frase única: tucano-sentinela-9931.
"""


@pytest.fixture(scope="module")
def registry_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("registry")
    build_forest(root / "amazonia")
    build_forest(root / "cerrado")
    # marker exists ONLY in amazonia; first-touch reindex must pick it up
    (root / "amazonia" / "notas" / "marcador-amazonia.md").write_text(
        MARKER_NODE, encoding="utf-8")
    (root / "nao-floresta").mkdir()  # directory without _index.md
    return root


class TestForestPool:
    @pytest.fixture()
    def pool(self, registry_root):
        p = ForestPool(root=registry_root, writable=False)
        yield p
        p.close()

    def test_list_and_lazy_activation(self, pool):
        listing = pool.list()
        assert listing["mode"] == "registry"
        ids = {f["id"]: f["active"] for f in listing["forests"]}
        assert ids == {"amazonia": False, "cerrado": False}  # nao-floresta excluded
        pool.get("amazonia").locate("vendas")
        assert {f["id"]: f["active"] for f in pool.list()["forests"]}["amazonia"] is True

    def test_missing_forest_param_is_schema_error_with_hint(self, pool):
        with pytest.raises(VineError) as e:
            pool.get(None)
        assert e.value.code == E_SCHEMA
        assert "amazonia" in (e.value.hint or "")

    def test_isolation_between_forests(self, pool):
        hit = pool.get("amazonia").sniff(["tucano-sentinela-9931"])
        assert [r["id"] for r in hit["results"]] == ["notas/marcador-amazonia"]
        assert pool.get("cerrado").sniff(["tucano-sentinela-9931"])["results"] == []

    def test_path_escape_rejected(self, pool):
        for bad in ("../outside", "amazonia/../../etc"):
            with pytest.raises(VineError) as e:
                pool.get(bad)
            assert e.value.code == E_NOT_FOUND

    def test_non_forest_directory_rejected(self, pool):
        with pytest.raises(VineError) as e:
            pool.get("nao-floresta")
        assert e.value.code == E_NOT_FOUND

    def test_single_mode_backward_compat(self, registry_root):
        pool = ForestPool(single=registry_root / "amazonia", writable=False)
        try:
            assert pool.list()["mode"] == "single"
            assert pool.get(None).locate("vendas")["results"]  # no param needed
            assert pool.get("amazonia") is pool.get(None)  # name match ok
            with pytest.raises(VineError) as e:
                pool.get("cerrado")
            assert e.value.code == E_NOT_FOUND
        finally:
            pool.close()


class TestRegistryOverMcp:
    def test_stdio_registry_end_to_end(self, registry_root):
        """Full protocol path: spawn `vine serve --root`, pick forests per call."""

        async def go():
            from mcp import ClientSession
            from mcp.client.stdio import StdioServerParameters, stdio_client

            env = dict(os.environ)
            env["PYTHONPATH"] = str(REPO / "src") + os.pathsep + env.get("PYTHONPATH", "")
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "monkeyllm.cli", "serve", "--root", str(registry_root), "--readonly"],
                env=env,
                cwd=str(REPO),
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    r = await session.call_tool("forests", {})
                    listing = json.loads(r.content[0].text)
                    assert {f["id"] for f in listing["forests"]} == {"amazonia", "cerrado"}

                    r = await session.call_tool(
                        "sniff", {"terms": ["tucano-sentinela-9931"], "forest": "amazonia"})
                    assert json.loads(r.content[0].text)["results"]

                    r = await session.call_tool("locate", {"query": "vendas"})  # no forest
                    out = json.loads(r.content[0].text)
                    assert out["error"]["code"] == E_SCHEMA

        anyio.run(go)
