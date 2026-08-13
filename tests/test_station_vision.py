# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The G.5.1 vision describer (host side).

The model is faked here, so what is under test is the converter contract
around it: the None-means-stub seam, the exact multimodal message shape
sent to an OpenAI-compatible endpoint, the size refusal, and the rule
that an empty description raises — because in the Gardener's chain,
raising IS the fallback path to the stub.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

from monkeyllm.errors import VineError  # noqa: E402
from monkeyllm.gardener import Conversion  # noqa: E402
from monkeyllm_station.vision import (  # noqa: E402
    MAX_IMAGE_BYTES, PROMPT, image_converter,
)

BINDING = {"endpoint": "http://localhost:1", "model": "fake-vision"}


def fake_factory(reply: str, captured: list):
    """A chat factory that answers from a can and records what it saw —
    the (chat, model) tuple shape `chat_from_binding` returns."""

    def factory(binding):
        def chat(messages):
            captured.append(messages)
            return reply
        return chat, binding.get("model", "fake-vision")

    return factory


def test_no_binding_means_no_converter():
    # No vision role bound -> None, and the engine stub keeps claiming the
    # image extensions. A supported state, not a degraded one.
    assert image_converter(None) is None


def test_extensions_are_the_image_set():
    conv = image_converter(BINDING, _chat_factory=fake_factory("x", []))
    assert conv.extensions == {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def test_convert_yields_markdown_with_the_description(tmp_path):
    (tmp_path / "team-org_chart.png").write_bytes(b"\x89PNG fake bytes")
    captured: list = []
    conv = image_converter(
        BINDING,
        _chat_factory=fake_factory(
            "A flowchart of the team.\n\n- CEO -> CTO", captured),
    )

    result = conv.convert(tmp_path / "team-org_chart.png")

    assert isinstance(result, Conversion)
    assert result.kind == "markdown"
    # Title from the filename stem, humanised the way the built-ins do it.
    assert result.title == "team org chart"
    assert result.markdown.startswith("# team org chart\n\n")
    assert "A flowchart of the team." in result.markdown
    assert "CEO -> CTO" in result.markdown


@pytest.mark.parametrize("name,mime", [
    ("shot.png", "image/png"),
    ("photo.jpg", "image/jpeg"),
    ("photo.jpeg", "image/jpeg"),
    ("anim.gif", "image/gif"),
    ("modern.webp", "image/webp"),
])
def test_data_url_carries_the_right_mime_and_the_file_bytes(
        tmp_path, name, mime):
    payload = b"not really an image, but the bytes are the contract"
    (tmp_path / name).write_bytes(payload)
    captured: list = []
    conv = image_converter(BINDING,
                           _chat_factory=fake_factory("described", captured))

    conv.convert(tmp_path / name)

    # ONE user message whose content is a list of two parts: the prompt,
    # then the image — the shape /chat/completions receives verbatim.
    assert len(captured) == 1
    (message,) = captured[0]
    assert message["role"] == "user"
    text_part, image_part = message["content"]
    assert text_part == {"type": "text", "text": PROMPT}
    assert image_part["type"] == "image_url"
    url = image_part["image_url"]["url"]
    prefix = f"data:{mime};base64,"
    assert url.startswith(prefix)
    # Valid base64, and of exactly the file's bytes — a data URL of
    # anything else describes a different image than the one adopted.
    assert base64.b64decode(url[len(prefix):], validate=True) == payload


def test_empty_reply_raises_for_the_stub_fallback(tmp_path):
    (tmp_path / "blank.png").write_bytes(b"png-ish")
    conv = image_converter(BINDING, _chat_factory=fake_factory("  \n\t ", []))

    # An empty description planted as a body would look like success while
    # being worse than the stub; raising hands the file back to the chain.
    with pytest.raises(VineError):
        conv.convert(tmp_path / "blank.png")


def test_oversized_image_is_refused_before_any_model_call(tmp_path):
    (tmp_path / "huge.png").write_bytes(b"\x00" * (MAX_IMAGE_BYTES + 1))
    captured: list = []
    conv = image_converter(BINDING,
                           _chat_factory=fake_factory("never", captured))

    with pytest.raises(VineError):
        conv.convert(tmp_path / "huge.png")
    # The refusal is cheaper than the provider's: no call was spent.
    assert captured == []


def test_transport_errors_propagate(tmp_path):
    (tmp_path / "down.png").write_bytes(b"png-ish")

    def broken_factory(binding):
        def chat(messages):
            raise ConnectionError("endpoint down")
        return chat, "fake-vision"

    conv = image_converter(BINDING, _chat_factory=broken_factory)
    # The Gardener's chain catches converter exceptions and falls back to
    # the stub — so the describer never swallows one into a fake success.
    with pytest.raises(ConnectionError):
        conv.convert(tmp_path / "down.png")


def test_production_factory_pins_the_lane_hold_timeout(tmp_path, monkeypatch):
    """G.5.1 (v0.48): the describer's call runs inside a convert stage,
    which holds the forest's ONE lane — every reader of that forest waits
    behind it. So the default factory MUST pass timeout=60.0 to
    `chat_from_binding` instead of inheriting its 180-second chat-surface
    default: three minutes of patience here is a frozen console."""
    from monkeyllm_station import inference

    captured: dict = {}

    def fake_chat_from_binding(binding, *, timeout=180.0):
        captured["binding"] = binding
        captured["timeout"] = timeout

        def chat(messages):
            return "described"

        return chat, "fake-vision"

    monkeypatch.setattr(inference, "chat_from_binding", fake_chat_from_binding)
    (tmp_path / "shot.png").write_bytes(b"png-ish")

    # No _chat_factory: this is the production path, wrapper included.
    conv = image_converter(BINDING)
    result = conv.convert(tmp_path / "shot.png")

    assert captured["timeout"] == 60.0
    assert captured["binding"] is conv._binding
    assert result.kind == "markdown"
