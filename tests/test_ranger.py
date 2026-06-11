"""Part H (spec v0.10): the Ranger — evaporation, promotion/pruning, health."""

import subprocess
import time

import pytest

from monkeyllm.ranger import Ranger

DAY = 86400.0


@pytest.fixture()
def clock():
    """Synthetic clock: starts at real now, advances on demand (F.14)."""
    state = {"t": time.time()}

    class Clock:
        def __call__(self):
            return state["t"]

        def advance(self, seconds: float):
            state["t"] += seconds

    return Clock()


@pytest.fixture()
def ranger(vine_rw, clock):
    return Ranger(vine_rw, now=clock), clock


class TestEvaporation:
    def test_one_half_life_halves_heat(self, vine_rw, ranger):
        r, clock = ranger
        vine_rw.trails.add_heat(["conceitos/rag"], amount=0.8)
        vine_rw.trails.set_updated("conceitos/rag", clock())
        clock.advance(30 * DAY)  # exactly one default half-life
        r.evaporate()
        assert abs(vine_rw.trails.get_heat("conceitos/rag") - 0.4) < 0.01

    def test_dust_rows_vanish(self, vine_rw, ranger):
        r, clock = ranger
        vine_rw.trails.add_heat(["conceitos/rag"], amount=0.05)
        vine_rw.trails.set_updated("conceitos/rag", clock())
        clock.advance(120 * DAY)  # 4 half-lives: 0.05 -> ~0.003 < 0.01 floor
        report = r.evaporate()
        assert report["removed"] == 1
        assert vine_rw.trails.get_heat("conceitos/rag") == 0.0
        assert vine_rw.trails.stats()["rows"] == 0

    def test_back_to_back_runs_are_idempotent(self, vine_rw, ranger):
        r, clock = ranger
        vine_rw.trails.add_heat(["conceitos/rag"], amount=0.8)
        vine_rw.trails.set_updated("conceitos/rag", clock())
        clock.advance(15 * DAY)
        r.evaporate()
        h1 = vine_rw.trails.get_heat("conceitos/rag")
        r.evaporate()  # same clock instant: must not decay again
        assert vine_rw.trails.get_heat("conceitos/rag") == h1

    def test_stale_sessions_cleared(self, vine_rw, ranger):
        r, clock = ranger
        vine_rw.trails.add_heat(["conceitos/rag"], amount=0.5, scope="hunt-42")
        vine_rw.trails.set_updated("conceitos/rag", clock(), scope="hunt-42")
        clock.advance(25 * 3600)  # past the 24h TTL
        report = r.evaporate()
        assert report["stale_sessions_cleared"] == 1
        assert vine_rw.trails.get_heat("conceitos/rag", session="hunt-42") == 0.0


class TestLinkTending:
    SHORTCUT = {"rel": "discovered-shortcut", "target": "conceitos/rag",
                "confidence": 0.5, "discovered_by": "agent"}

    def _add_shortcut(self, vine, source="projetos/mixerllm/arquitetura"):
        vine.graft(source, {"add_links": [self.SHORTCUT]})
        return source

    def test_hot_proposal_is_promoted_with_audited_commit(self, vine_rw, ranger, forest_rw):
        r, _ = ranger
        src = self._add_shortcut(vine_rw)
        vine_rw.trails.add_heat([src, "conceitos/rag"], amount=0.4)  # well used
        report = r.tend_links()
        assert report["promoted"] == [f"{src} discovered-shortcut->conceitos/rag"]
        assert report["pruned"] == []

        link = [l for l in vine_rw.forest.read(src).frontmatter["links"]
                if l.get("rel") == "discovered-shortcut"][0]
        assert link["confidence"] == 0.8
        head = subprocess.run(["git", "-C", str(forest_rw), "log", "-1", "--pretty=%s"],
                              capture_output=True, text=True, check=True).stdout
        assert head.startswith(f"ranger(promote): {src}")

    def test_cold_proposal_is_pruned(self, vine_rw, ranger, clock):
        r, _ = ranger
        src = self._add_shortcut(vine_rw)
        # graft fortification deposited heat; let it fully evaporate
        clock.advance(400 * DAY)
        r.evaporate()
        report = r.tend_links()
        assert report["pruned"] == [f"{src} discovered-shortcut->conceitos/rag"]
        links = vine_rw.forest.read(src).frontmatter.get("links") or []
        assert not [l for l in links if l.get("rel") == "discovered-shortcut"]

    def test_warm_proposal_is_left_alone(self, vine_rw, ranger):
        """Neither hot enough to promote nor cold enough to prune."""
        r, _ = ranger
        src = self._add_shortcut(vine_rw)
        vine_rw.trails.add_heat([src, "conceitos/rag"], amount=0.1)  # below floor
        report = r.tend_links()
        assert report["promoted"] == [] and report["pruned"] == []
        link = [l for l in vine_rw.forest.read(src).frontmatter["links"]
                if l.get("rel") == "discovered-shortcut"][0]
        assert link["confidence"] == 0.5

    def test_full_confidence_links_are_never_touched(self, vine_rw, ranger, clock):
        """Structural edges and confidence-1.0 links are outside H.2 scope."""
        r, _ = ranger
        node = vine_rw.forest.read("projetos/mixerllm/arquitetura")
        before = list(node.frontmatter.get("links") or [])
        assert before  # fixture node has structural links
        clock.advance(400 * DAY)  # everything stone cold
        r.evaporate()
        report = r.tend_links()
        assert report["pruned"] == []
        assert (vine_rw.forest.read("projetos/mixerllm/arquitetura")
                .frontmatter.get("links") or []) == before

    def test_promotion_is_idempotent(self, vine_rw, ranger):
        r, _ = ranger
        src = self._add_shortcut(vine_rw)
        vine_rw.trails.add_heat([src, "conceitos/rag"], amount=0.4)
        assert len(r.tend_links()["promoted"]) == 1
        assert r.tend_links() == {"promoted": [], "pruned": []}


class TestHealth:
    def test_health_flags_problems(self, vine_rw, ranger, forest_rw):
        r, _ = ranger
        # fabricate a fat branch (over the entry threshold)
        fat = forest_rw / "vendas" / "_index.md"
        body = fat.read_text(encoding="utf-8")
        extra = "\n".join(f"- [[vendas/fake-{i}]] — fake entry." for i in range(160))
        fat.write_text(body + "\n" + extra, encoding="utf-8")
        # a passport whose source is gone
        (forest_rw / "_meta").mkdir(exist_ok=True)
        (forest_rw / "_meta" / "gardener.yaml").write_text(
            f"source_root: {forest_rw.as_posix()}/nope\n", encoding="utf-8")
        vine_rw.graft("conceitos/rag", {"set_frontmatter": {"tags": ["x"]}})  # touch nothing relevant
        node_path = forest_rw / "conceitos" / "rag.md"
        text = node_path.read_text(encoding="utf-8")
        node_path.write_text(text.replace("tags:", "source_path: sumiu.md\ntags:", 1),
                             encoding="utf-8")

        report = r.health()
        assert "vendas/_index" in report["needs_split"]
        assert "conceitos/rag" in report["stale_passports"]
        assert report["lint"]["errors"] >= 0 and "heat" in report

    def test_uncertain_inventory_buckets(self, vine_rw, ranger):
        r, _ = ranger
        vine_rw.graft("projetos/mixerllm/arquitetura", {"add_links": [
            {"rel": "discovered-shortcut", "target": "conceitos/rag",
             "confidence": 0.5}]})
        report = r.health()
        assert report["uncertain_links"].get("0.5", 0) >= 1


class TestFullCycle:
    def test_run_returns_all_sections(self, ranger):
        r, _ = ranger
        report = r.run()
        assert set(report) == {"evaporation", "payload_cache", "links", "health"}
