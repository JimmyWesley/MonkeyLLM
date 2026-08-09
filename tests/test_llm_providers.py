# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Provider resolution for the navigator LLM (local / OpenRouter / HF)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "demo"))

from run_demo import OPENROUTER_DEFAULT_MODEL, OPENROUTER_ENDPOINT, resolve_provider  # noqa: E402

ALL_VARS = ["MONKEYLLM_LLM_ENDPOINT", "MONKEYLLM_LLM_MODEL", "MONKEYLLM_LLM_API_KEY",
            "OPENROUTER_API_KEY", "HF_TOKEN"]


def clean(monkeypatch):
    for v in ALL_VARS:
        monkeypatch.delenv(v, raising=False)


class TestResolveProvider:
    def test_explicit_endpoint_wins(self, monkeypatch):
        clean(monkeypatch)
        monkeypatch.setenv("MONKEYLLM_LLM_ENDPOINT", "http://localhost:8090/v1")
        monkeypatch.setenv("MONKEYLLM_LLM_MODEL", "gemma-4")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")  # must NOT override explicit endpoint
        endpoint, model, key = resolve_provider()
        assert endpoint == "http://localhost:8090/v1"
        assert model == "gemma-4"

    def test_openrouter_when_key_present(self, monkeypatch):
        clean(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
        endpoint, model, key = resolve_provider()
        assert endpoint == OPENROUTER_ENDPOINT
        assert model == OPENROUTER_DEFAULT_MODEL
        assert key == "sk-or-x"

    def test_openrouter_respects_model_override(self, monkeypatch):
        clean(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
        monkeypatch.setenv("MONKEYLLM_LLM_MODEL", "openai/gpt-oss-20b")
        _, model, _ = resolve_provider()
        assert model == "openai/gpt-oss-20b"

    def test_hf_serverless_fallback(self, monkeypatch):
        clean(monkeypatch)
        monkeypatch.setenv("HF_TOKEN", "hf_x")
        endpoint, model, key = resolve_provider()
        assert endpoint is None
        assert key == "hf_x"
