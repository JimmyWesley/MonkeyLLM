<!-- SPDX-License-Identifier: Apache-2.0 -->

# Whisper — audio your forest can search

Ingest a recording; get a `media` node that keeps the audio **and** carries
its transcript as the body. `locate` finds it by what it is about; `sniff`
finds it by a word that was only ever spoken.

It is the audio half of what the vision describer does for images, and it
matters for the same reason: payload bytes never enter model material
(J.14), so the text written at ingest is all a model will ever know about
the recording. A meeting whose words were never written down is a meeting no
search will land in.

## What it needs

Nothing installed. A transcription is a multipart upload, which the host
already knows how to make — so this extension adds **no package** to the
engine's environment. That is the point of it.

What it does need is a **model bound to the `transcribe` role**, which the
extension registers and an operator binds like any other. The endpoint and
the credential stay under the host's custody (J.10.2): this extension never
receives either, and its spend is metered, capped and audited under whoever
caused it.

## Setting it up

```bash
vine ext install github.com/JimmyWesley/MonkeyLLM@v0.80.0#extensions/whisper
```

Then, on the Station: **Extensions → enable it on your forest**, and
**Models → add a provider → bind `transcribe`**.

- Provider endpoint: `https://api.openai.com/v1`
- Model: `whisper-1`, or `gpt-4o-transcribe` for better punctuation
- The API key goes in the **provider**, never in this extension. It is
  write-only over the API: it goes in, and comes back only as `has_value`.

From the CLI instead:

```bash
vine ext enable whisper --forest /path/to/forest
vine ext config whisper --set language=pt --set vocabulary="Plastexpress, BE-291"
```

Restart the host after installing. Settings take effect immediately.

## Settings


| Setting      | What it does                                                                                                                                                                            |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `language`   | A BCP-47 hint (`pt`, `en`). Empty lets the model detect. Setting it is usually worth it: detection costs accuracy on the first seconds.                                                 |
| `vocabulary` | Names, jargon and acronyms the recording uses, comma separated. This is a**decoder bias**, not an instruction — it is sent verbatim, so write the spellings you want and nothing else. |
| `heading`    | The heading the transcript is written under.`Ata` reads better than `Transcript` on a Portuguese forest.                                                                                |

## What it will not do

- **Files over 25 MB are refused**, before the upload rather than after —
  spending the transfer to be told no holds the forest's lane for as long as
  it takes. Split a long recording, or transcribe it elsewhere and ingest
  the text.
- **It never guesses.** An empty transcription, a provider that is down, an
  unbound role: each raises, and the Gardener falls back to the built-in
  stub. You get a findable-by-name media node with "no description yet",
  which a later `sync` fills in — never a lost file, never a half-written
  body presented as a transcript.
- **The duration it prints is an estimate** from the file size, and says so.
  Reading a real duration means a media library, which is the dependency
  this extension exists to avoid.

## The cost worth knowing

The call runs inside a Gardener step, and a step holds that forest's single
lane: every read on that forest waits behind it. A long recording is
therefore a real pause, bounded by `MONKEYLLM_TRANSCRIBE_TIMEOUT` (300s by
default). Ingest recordings in batches you are willing to wait for.
