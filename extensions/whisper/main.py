# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Whisper — an audio file becomes a transcript the forest can search.

This is the audio half of what the vision describer (G.5.1) does for
images, and it is deliberately built the same way, because the reason is
the same: **the text written here at ingest is all a model will ever know
about the recording.** J.14 keeps payload bytes out of model material, so
`locate` searches the scent this produces and `sniff` greps this body and
nothing else. A meeting whose words were never written down is a meeting
no search will ever land in.

Three properties it inherits from the built-in chain rather than inventing:

- **The node is still `media`.** Type follows the payload, not the
  conversion, so the audio is archived and `view`/the payload route still
  serve the bytes. The transcript is the node's body, not a replacement
  for the recording.
- **Failure IS the fallback.** Every refusal here raises, and the Gardener
  falls down the chain to the built-in stub — format, size, "no
  description yet". A provider that is down produces a findable-by-name
  node that a later `sync` can fill in, never a lost file and never a
  half-written one.
- **It holds no key.** The transcription runs through
  `api.models.transcribe`, so the endpoint and the credential stay under
  the host's custody (J.10.2) and the spend is metered, quota'd and
  audited under the person who caused it (L.7).

It also carries no dependency. An OpenAI-compatible transcription is a
multipart upload, which the host already knows how to make — which is the
whole point of the exercise: the capability arrives without a single
package entering the engine's own environment.
"""

from __future__ import annotations

import os
from pathlib import Path

# The prompt field of a transcription API is not an instruction, it is a
# VOCABULARY hint: the decoder is biased toward the spellings it contains.
# So the operator's `vocabulary` setting goes here verbatim, and no English
# sentence is wrapped around it — a sentence would bias the decoder toward
# transcribing that sentence.
_MAX_HINT = 900          # providers clip this field; clip it ourselves first

_API = {"api": None}     # set by register(), read by convert()


def register(api):
    """Activation. The only thing kept is the host's own surface."""
    _API["api"] = api


def _settings() -> dict:
    api = _API["api"]
    return dict(getattr(api, "config", None) or {}) if api else {}


def _title(path: Path) -> str:
    stem = path.stem.replace("_", " ").replace("-", " ").strip()
    return stem or path.stem


def convert(path):
    """The G.2 converter contract: a file in, a `Conversion` out.

    Returns a plain dict rather than importing the engine's dataclass: an
    extension is coupled to the seam's published shape, never to the class
    behind it, and the adapter builds the real object on the host side.
    """
    api = _API["api"]
    if api is None:                       # register() never ran
        raise RuntimeError("whisper: the extension was not activated")

    audio = Path(path)
    settings = _settings()

    hint = (settings.get("vocabulary") or "").strip()[:_MAX_HINT] or None
    language = (settings.get("language") or "").strip() or None

    text = api.models.transcribe(
        role="transcribe", audio=str(audio),
        language=language, prompt=hint)

    transcript = (text or "").strip()
    if not transcript:
        # The host already refuses an empty answer; this is the second
        # reader of the same fact, and it costs nothing to be sure — an
        # empty body would look like success and be worse than the stub.
        raise RuntimeError("whisper: the transcription came back empty")

    title = _title(audio)
    heading = (settings.get("heading") or "Transcript").strip() or "Transcript"
    size = audio.stat().st_size
    minutes = _minutes(size)

    body = [f"# {title}", ""]
    body.append(f"Audio recording `{audio.name}` "
                f"({audio.suffix.lstrip('.').upper()}, {size} bytes"
                + (f", about {minutes}" if minutes else "") + ").")
    body.append("")
    body.append(f"## {heading}")
    body.append("")
    body.append(transcript)
    body.append("")

    return {"kind": "markdown", "title": title, "markdown": "\n".join(body)}


def _minutes(size: int) -> str:
    """A rough duration from the file size, and honest about being rough.

    Reading the real duration means a media library, which is exactly the
    dependency this extension exists to avoid. ~1 MB per minute is the
    common 128 kbps MP3, so it is stated as an approximation and never as
    a fact — a wrong number presented as measured is worse than no number.
    """
    if size <= 0:
        return ""
    approx = max(1, round(size / (1024 * 1024)))
    return f"{approx} minute{'s' if approx != 1 else ''} at 128 kbps"
