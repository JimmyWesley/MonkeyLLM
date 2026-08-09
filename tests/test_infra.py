"""Writer lock, CLI, MCP server surface, latency budgets (Part F criterion 6)."""

import asyncio
import statistics
import time

import pytest

from monkeyllm import Vine
from monkeyllm.errors import E_LOCKED, VineError


class TestWriterLock:
    def test_single_writer_per_forest(self, forest_rw):
        v1 = Vine(forest_rw, writable=True)
        try:
            with pytest.raises(VineError) as e:
                Vine(forest_rw, writable=True)
            assert e.value.code == E_LOCKED
        finally:
            v1.close()
        v2 = Vine(forest_rw, writable=True)  # lock released
        v2.close()

    def test_readers_never_block(self, forest_rw):
        v1 = Vine(forest_rw, writable=True)
        try:
            r = Vine(forest_rw, writable=False)
            assert r.look("_index")["id"] == "_index"
            r.close()
        finally:
            v1.close()


class TestCLI:
    def test_validate_clean_forest(self, forest_ro, capsys):
        from monkeyllm.cli import main

        assert main(["validate", "--forest", str(forest_ro)]) == 0
        assert "0 error(s)" in capsys.readouterr().out

    def test_reindex(self, forest_ro, capsys):
        from monkeyllm.cli import main

        assert main(["reindex", "--forest", str(forest_ro)]) == 0
        assert "reindexed 82 nodes" in capsys.readouterr().out


class TestMCPServer:
    def test_all_primitives_exposed(self, forest_ro):
        from monkeyllm.server import build_server

        server = build_server(forest_ro, writable=False)
        try:
            tools = {t.name for t in asyncio.run(server.list_tools())}
            assert {"locate", "look", "move", "pick", "query", "scan", "plant", "graft", "close_session"} <= tools
        finally:
            server._close()

    def test_error_envelope(self, forest_ro):
        from monkeyllm.server import build_server

        server = build_server(forest_ro, writable=False)
        try:
            result = asyncio.run(server.call_tool("look", {"id": "nao/existe"}))
            assert "E_NOT_FOUND" in str(result)
        finally:
            server._close()


def p95(samples):
    return statistics.quantiles(samples, n=20)[-1]


class TestLatency:
    """Spec Part F.6: p95 look/move/pick < 10ms, query < 50ms, locate < 100ms."""

    def _measure(self, fn, n=40):
        samples = []
        for _ in range(n):
            t0 = time.perf_counter()
            fn()
            samples.append((time.perf_counter() - t0) * 1000)
        return p95(samples)

    def test_look_move_pick_p95_under_10ms(self, vine_ro):
        assert self._measure(lambda: vine_ro.look("projects/mixerllm/architecture")) < 10
        assert self._measure(lambda: vine_ro.move("projects/mixerllm/architecture")) < 10
        assert self._measure(lambda: vine_ro.pick("concepts/rag")) < 10

    def test_query_p95_under_50ms(self, vine_ro):
        assert self._measure(
            lambda: vine_ro.query(
                "sales/report-q1-2026",
                "SELECT region, SUM(value) FROM sales GROUP BY region",
            )
        ) < 50

    def test_locate_p95_under_100ms(self, vine_ro):
        assert self._measure(lambda: vine_ro.locate("inference architecture")) < 100
