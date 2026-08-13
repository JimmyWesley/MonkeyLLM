# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Jimmy Wesley

"""The G.5.1 vision describer: an image becomes findable text, once.

This is the ONE place a model sees the image. J.14 keeps payload bytes out
of model material everywhere else — the payload endpoint is a human
surface, `answer` and the walk read the textual proxy — so the description
written here at ingest is all a model will ever know about the picture.
That is by design (G.5: text to find, binary to consume), and it is why
the prompt insists on transcription: `sniff` reads only the proxy, and a
slide whose bullet points were never written down is a slide no exact-term
search will ever land in.

The describer is a host resource because the model is one (J.10): the
engine never holds a model, so the engine ships the stub — format, size,
"no description available yet" — and the host injects this converter
through the Gardener's `extra_converters` seam, ranked between the
operator's command hooks and the built-ins. An operator who configured
their own `.png` command hook keeps it; everyone else gets the describer
over the stub.

Failure IS the fallback path: the Gardener catches converter exceptions
and falls back down the chain to the stub (G.4.3's rule reaching
conversion), so every refusal here — oversized file, empty reply,
endpoint down — raises rather than degrades silently. A broken model
never aborts ingest; it produces a stub node the describer can replace
on a later sync.
"""

from __future__ import annotations

import base64
from pathlib import Path

from monkeyllm.errors import E_SCHEMA, VineError
from monkeyllm.gardener import Conversion

# What the vision model is asked for. Transcription is the load-bearing
# half: the description makes the image findable by `locate` (curated
# scent), but only the verbatim text — labels, code, box-and-arrow
# structure — makes a slide or a flowchart findable by `sniff`, which
# greps the textual proxy and nothing else (G.5).
PROMPT = (
    "Describe this image for a knowledge index. State plainly what it "
    "shows, then transcribe any legible text in it — labels, headings, "
    "code, and the structure of any diagram (boxes, arrows, what connects "
    "to what). Reply in plain markdown, no preamble."
)

# The MIME type is part of the data URL contract: a provider that trusts
# the declared type over the bytes would mis-decode a mislabelled image,
# so the label comes from the extension the converter claimed, never from
# a guess over the content.
MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# ~6 MB of raw bytes is ~8 MB of base64 — past that, providers start
# refusing the request body and the call spends its timeout to fail.
# Refusing here is cheaper and lands in the same place: the stub.
MAX_IMAGE_BYTES = 6 * 1024 * 1024

# G.5.1 (v0.48): the describer's call runs inside the convert stage of a
# step, and a step holds the forest's ONE lane (J.9) — every read on the
# forest, every console open on it, waits behind this call. The 180-second
# patience `chat_from_binding` defaults to suits a chat surface; here it is
# a frozen panel, so the ceiling is 60 seconds. A timeout raises out of
# `convert` and falls back to the stub like any other failure, with the
# reason in the report's errors.
DESCRIBER_TIMEOUT = 60.0


class VisionDescriber:
    """A G.2 converter whose `convert` is one model call.

    Same contract as every built-in — `extensions` + `convert(path) ->
    Conversion` — so the Gardener needs no special case: it ranks in the
    chain like any other converter and its exceptions fall through to the
    stub like any other converter's.
    """

    extensions = set(MIME_BY_EXT)

    def __init__(self, binding: dict, chat_factory):
        self._binding = binding
        self._chat_factory = chat_factory

    def convert(self, path: Path) -> Conversion:
        path = Path(path)
        mime = MIME_BY_EXT.get(path.suffix.lower())
        if mime is None:
            # The Gardener only routes claimed extensions here, so this is
            # a programming error surfacing early rather than a data URL
            # with a wrong label surfacing as a provider 400.
            raise VineError(E_SCHEMA,
                            f"not a describable image extension: {path.suffix!r}")

        data = path.read_bytes()
        if len(data) > MAX_IMAGE_BYTES:
            raise VineError(
                E_SCHEMA,
                f"image is {len(data)} bytes, over the "
                f"{MAX_IMAGE_BYTES}-byte describer limit",
                hint="the stub converter records format and size instead",
            )

        data_url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"

        # ONE user message whose content is a list of parts. The messages
        # pass through `chat_from_binding` to an OpenAI-compatible
        # /chat/completions verbatim, so multimodal content-parts need no
        # support from the client — the shape here is the whole contract.
        chat, _model = self._chat_factory(self._binding)
        reply = chat([{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }])

        description = (reply or "").strip()
        if not description:
            # A model that returned nothing described nothing. Planting an
            # empty body would look like success while being worse than
            # the stub, which at least states format and size.
            raise VineError(E_SCHEMA, "vision model returned an empty description")

        # Title from the filename, the same way the markdown built-in
        # falls back: the file name is the only prose the source offers.
        title = path.stem.replace("_", " ").replace("-", " ").strip() or path.stem
        return Conversion(kind="markdown", title=title,
                          markdown=f"# {title}\n\n" + description)


def image_converter(binding: dict | None, *, _chat_factory=None):
    """The forest's `vision` binding as a converter, or None.

    None is a supported state, not a degraded one (same rule as
    `curator_from_binding`): with no vision model bound, the engine's
    built-in stub claims the image extensions and the forest still
    ingests. `_chat_factory` exists for tests — production always speaks
    through `inference.chat_from_binding`, whose transport and HTTP
    errors propagate so the Gardener's fallback chain sees them. A test
    factory receives `(binding)` alone and may ignore the timeout; the
    production wrapper is where the 60-second lane-hold ceiling is
    applied, because the seam's contract is "a chat for this binding"
    and the deadline is this call site's fact, not the binding's.
    """
    if not binding:
        return None
    if _chat_factory is None:
        def _chat_factory(b):
            # Resolved at call time so the timeout travels with EVERY
            # request the describer makes (G.5.1: the call holds the
            # forest's lane, so 60 s is the most a reader ever waits).
            from monkeyllm_station import inference

            return inference.chat_from_binding(b, timeout=DESCRIBER_TIMEOUT)
    return VisionDescriber(binding, _chat_factory)
