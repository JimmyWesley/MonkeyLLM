# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The reply has a stated size (spec v0.48, J.10.8 — F.51), and the answer
that shows what it read (J.10.9, prompt half).

`reply_tokens` is a per-call override of the binding's `max_tokens`:
clamped to [64, 4000], stated in the prompt so the model shapes the reply
instead of being cut mid-sentence, and part of the J.10.7 key when set —
a short answer and a long answer to one question are two entries. Absent,
everything keys and behaves byte-for-byte as before the upgrade.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"
QUESTION = "architecture notes"


@pytest.fixture(scope="session")
def reply_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("reply-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def station(reply_root, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station import inference
    from monkeyllm_station.app import build_app

    seen: list[dict] = []      # the kwargs each provider client was built with
    prompts: list[list] = []   # the messages of each provider round trip

    def fake(binding, **kw):
        seen.append(kw)

        def chat(messages):
            prompts.append(messages)
            return f"stub answer #{len(prompts)}"
        return chat, binding.get("model", "stub-model")

    monkeypatch.setattr(inference, "chat_from_binding", fake)
    shutil.rmtree(reply_root / FOREST / "_derived" / "cache",
                  ignore_errors=True)

    app = build_app(root=reply_root, registry_path=tmp_path / "station.db",
                    mcp=False)
    registry = app.state.registry
    key = registry.issue_key("root")
    registry.grant("root", FOREST, {"admin", "read", "query", "write"})
    registry.put_provider("p", "http://stub/v1", None)
    registry.bind_model(FOREST, "answer", "p", "stub-model")
    with TestClient(app) as client:
        yield client, seen, prompts, {"Authorization": f"Bearer {key}"}


def _ask(client, head, **body):
    r = client.post(f"/v1/forests/{FOREST}/answer",
                    json={"question": QUESTION, **body}, headers=head)
    assert r.status_code == 200, r.text
    return r.json()


# -- the override reaches the provider call ----------------------------------


def test_reply_tokens_caps_the_call_and_is_stated(station):
    client, seen, prompts, head = station
    _ask(client, head, reply_tokens=200)
    assert seen[-1]["reply_tokens"] == 200
    system = prompts[-1][0]["content"]
    assert "200 tokens" in system
    assert "150 words" in system  # ~0.75 words per token, said in words too


def test_absent_means_the_binding_rules_as_before(station):
    client, seen, prompts, head = station
    _ask(client, head)
    assert seen[-1].get("reply_tokens") is None
    assert "tokens (roughly" not in prompts[-1][0]["content"]


def test_the_value_is_clamped_to_the_stated_bounds(station):
    client, seen, _, head = station
    _ask(client, head, reply_tokens=999999, cache=False)
    assert seen[-1]["reply_tokens"] == 4000
    _ask(client, head, reply_tokens=1, cache=False)
    assert seen[-1]["reply_tokens"] == 64


def test_garbage_is_refused_not_guessed(station):
    client, _, _, head = station
    r = client.post(f"/v1/forests/{FOREST}/answer",
                    json={"question": QUESTION, "reply_tokens": "long"},
                    headers=head)
    assert r.json()["error"]["code"] == "E_SCHEMA"


def test_the_walk_states_it_for_the_final_answer(station):
    client, seen, prompts, head = station
    _ask(client, head, hops=2, reply_tokens=300)
    assert seen[-1]["reply_tokens"] == 300
    assert "final answer" in prompts[-1][0]["content"]


# -- the key (J.10.7) ---------------------------------------------------------


def test_two_sizes_are_two_entries_and_absent_keys_as_before(station):
    client, seen, _, head = station
    _ask(client, head, reply_tokens=200)
    assert len(seen) == 1
    served = _ask(client, head, reply_tokens=200)
    assert len(seen) == 1 and served["cached"] is True
    _ask(client, head, reply_tokens=400)
    assert len(seen) == 2, "a different size is a different answer"
    _ask(client, head)
    assert len(seen) == 3, "no size set is its own key — the pre-upgrade one"
    served = _ask(client, head)
    assert len(seen) == 3 and served["cached"] is True


# -- the fingerprint reads everything the model reads (J.10.7, v0.48) --------


def test_notes_enter_the_reading_fingerprint():
    from monkeyllm_station import answer_store

    def bundle(notes):
        item = {"id": "d", "type": "dataset", "title": "t", "summary": "s",
                "matches": [], "content": []}
        if notes is not None:
            item["notes"] = notes
        return {"results": [item], "truncated": False}

    taught = answer_store.reading_fingerprint(bundle("value is USD"))
    retaught = answer_store.reading_fingerprint(bundle("value is BRL"))
    untaught = answer_store.reading_fingerprint(bundle(None))
    assert taught != retaught, "a teaching edited is a reading changed"
    assert taught != untaught, "a teaching added is a reading changed"


# -- the media embed rule rides the prompt (J.10.9) ---------------------------


def test_media_in_the_bundle_teaches_the_embed_syntax(monkeypatch):
    from monkeyllm_station import inference

    prompts: list[list] = []

    def fake(binding, **_kw):
        def chat(messages):
            prompts.append(messages)
            return "ok"
        return chat, "stub-model"

    monkeypatch.setattr(inference, "chat_from_binding", fake)
    bundle = {"results": [
        {"id": "notes/shot", "type": "media", "title": "shot",
         "summary": "s", "matches": [], "content": []},
        {"id": "notes/plain", "type": "note", "title": "plain",
         "summary": "s", "matches": [], "content": []},
    ], "truncated": False}
    inference.answer(None, "q", {"model": "m"}, bundle=bundle)
    user = prompts[-1][-1]["content"]
    assert "ABOUT THE MEDIA" in user
    assert "notes/shot" in user
    assert "](media:<node id>)" in user

    prompts.clear()
    inference.answer(None, "q", {"model": "m"}, bundle={
        "results": [{"id": "notes/plain", "type": "note", "title": "p",
                     "summary": "s", "matches": [], "content": []}],
        "truncated": False})
    assert "ABOUT THE MEDIA" not in prompts[-1][-1]["content"]


def test_the_walk_prompt_carries_the_media_rule():
    from monkeyllm_station import inference

    assert "media:<node id>" in inference.FORAGE_SYSTEM


def test_clamp_reply_tokens_bounds():
    from monkeyllm_station import inference

    assert inference.clamp_reply_tokens(1) == 64
    assert inference.clamp_reply_tokens(300) == 300
    assert inference.clamp_reply_tokens(999999) == 4000
    with pytest.raises(ValueError):
        inference.clamp_reply_tokens("long")
