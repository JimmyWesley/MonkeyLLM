import pytest

from monkeyllm.errors import E_NOT_FOUND, E_SCHEMA, VineError
from monkeyllm.tokens import estimate_payload_tokens, estimate_tokens
from monkeyllm.vine import BUDGET_LOCATE, BUDGET_LOOK, BUDGET_MOVE, BUDGET_SCAN


class TestLocate:
    def test_contract_fields(self, vine_ro):
        r = vine_ro.locate("sales by region Q1 2026", k=5)
        assert "results" in r and "truncated" in r
        assert r["results"], "locate must find the sales region"
        top = r["results"][0]
        for key in ("id", "kind", "type", "title", "summary", "trail", "score", "heat"):
            assert key in top
        ids = [x["id"] for x in r["results"]]
        assert "sales/report-q1-2026" in ids

    def test_branch_results_are_landing_zones(self, vine_ro):
        r = vine_ro.locate("sales", scope="branches")
        assert r["results"]
        assert all(x["kind"] == "branch" for x in r["results"])
        assert any("coverage" in x for x in r["results"])

    def test_scope_bananas(self, vine_ro):
        r = vine_ro.locate("stigmergy ants", scope="bananas")
        assert all(x["kind"] == "banana" for x in r["results"])

    def test_type_filter(self, vine_ro):
        r = vine_ro.locate("sales", type_filter="dataset")
        assert all(x["type"] == "dataset" for x in r["results"])

    def test_k_and_budget(self, vine_ro):
        r = vine_ro.locate("projeto", k=3)
        assert len(r["results"]) <= 3
        assert estimate_payload_tokens(r) <= BUDGET_LOCATE

    def test_heat_reorders(self, vine_ro):
        cold = vine_ro.locate("inference hot cold model", k=5)
        target = cold["results"][1]["id"] if len(cold["results"]) > 1 else cold["results"][0]["id"]
        vine_ro.trails.add_heat([target], amount=0.9)
        hot = vine_ro.locate("inference hot cold model", k=5)
        t_cold = next(x for x in cold["results"] if x["id"] == target)
        t_hot = next(x for x in hot["results"] if x["id"] == target)
        assert t_hot["score"] > t_cold["score"]


class TestLook:
    def test_banana_digest_contract(self, vine_ro):
        d = vine_ro.look("projects/mixerllm/architecture")
        for key in ("id", "type", "title", "summary", "outline", "edges_out", "edges_in", "stats"):
            assert key in d, key
        assert d["stats"]["body_tokens"] > 0
        assert d["stats"]["degree"] >= len(d["edges_out"])
        rels = {e["rel"] for e in d["edges_out"]}
        assert "author" in rels and "compared-with" in rels

    def test_edges_in_use_derived_inverse(self, vine_ro):
        d = vine_ro.look("people/jimmy-wesley")
        in_rels = {e["rel"] for e in d["edges_in"]}
        assert "author-of" in in_rels  # jimmy declared author -> doc; doc side derived

    def test_branch_digest_has_children_and_cross_trails(self, vine_ro):
        d = vine_ro.look("sales/_index")
        assert "children" in d and "outline" not in d
        child_ids = {c["id"] for c in d["children"]}
        assert "sales/report-q1-2026" in child_ids
        assert "cross_trails" in d

    def test_dataset_digest_has_manual_and_sample(self, vine_ro):
        d = vine_ro.look("sales/report-q1-2026")
        assert "sales" in d["query_manual"]["tables"]
        assert d["query_manual"]["example_queries"]
        assert len(d["sample_rows"]["rows"]) <= 3

    def test_fields_filter(self, vine_ro):
        d = vine_ro.look("projects/mixerllm/architecture", fields=["summary", "edges_out"])
        assert set(d.keys()) <= {"id", "summary", "edges_out", "truncated"}
        assert d["id"] == "projects/mixerllm/architecture"

    def test_budget_for_every_node_in_forest(self, vine_ro):
        for node_id in vine_ro.forest.iter_ids():
            d = vine_ro.look(node_id)
            assert estimate_payload_tokens(d) <= BUDGET_LOOK, node_id

    def test_target_summary_truncated_to_25_tokens(self, vine_ro):
        d = vine_ro.look("projects/mixerllm/architecture")
        for e in d["edges_out"]:
            assert estimate_tokens(e["target_summary"]) <= 26

    def test_not_found(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.look("nao/existe")
        assert e.value.code == E_NOT_FOUND


class TestMove:
    def test_children_sugar(self, vine_ro):
        r = vine_ro.move("projects/mixerllm/_index", rel="children")
        ids = {n["id"] for n in r["neighbors"]}
        assert "projects/mixerllm/architecture" in ids

    def test_rel_filter_and_directions(self, vine_ro):
        out = vine_ro.move("projects/mixerllm/architecture", rel="author")
        assert [n["id"] for n in out["neighbors"]] == ["people/jimmy-wesley"]
        both = vine_ro.move("projects/mixerllm/architecture", direction="both")
        assert any(n["direction"] == "in" for n in both["neighbors"])

    def test_budget(self, vine_ro):
        r = vine_ro.move("organizations/tropicalia-tech", direction="both")
        assert estimate_payload_tokens(r) <= BUDGET_MOVE


class TestPick:
    def test_full_body(self, vine_ro):
        p = vine_ro.pick("concepts/stigmergy")
        assert p["truncated"] is False
        assert "modifying the environment" in p["body"]

    def test_section(self, vine_ro):
        p = vine_ro.pick("projects/mixerllm/architecture", section="Mixer-lang")
        assert p["section"] == "Mixer-lang"
        assert "delega" in p["body"]
        assert p["body_tokens"] < 200

    def test_giant_body_forces_section_navigation(self, vine_ro):
        p = vine_ro.pick("projects/mixerllm/experiment-log")
        assert p["truncated"] is True
        assert "body" not in p
        assert p["outline"]
        assert "section" in p["hint"]
        sec = vine_ro.pick("projects/mixerllm/experiment-log", section="Experiment 07")
        assert sec["truncated"] is False

    def test_missing_section(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.pick("concepts/stigmergy", section="Nothing")
        assert e.value.code == E_NOT_FOUND


class TestScan:
    def test_filter_type(self, vine_ro):
        r = vine_ro.scan("sales/_index", filter={"type": "dataset"})
        assert [n["id"] for n in r["nodes"]] == ["sales/report-q1-2026"]

    def test_recursive_with_tags(self, vine_ro):
        r = vine_ro.scan("_index", filter={"tags_any": ["benchmarks"]}, recursive=True)
        ids = {n["id"] for n in r["nodes"]}
        assert "projects/mixerllm/benchmarks" in ids

    def test_fields(self, vine_ro):
        r = vine_ro.scan("sales/_index", fields=["id", "summary", "payload_type"])
        ds = next(n for n in r["nodes"] if n["id"] == "sales/report-q1-2026")
        assert ds["payload_type"] == "sqlite"
        assert set(ds.keys()) == {"id", "summary", "payload_type"}

    def test_updated_after(self, vine_ro):
        r = vine_ro.scan("_index", filter={"updated_after": "2099-01-01"}, recursive=True)
        assert r["nodes"] == []

    def test_unknown_filter_rejected(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.scan("_index", filter={"vibe": "good"})
        assert e.value.code == E_SCHEMA

    def test_budget(self, vine_ro):
        r = vine_ro.scan("_index", recursive=True, limit=50)
        assert estimate_payload_tokens(r) <= BUDGET_SCAN
