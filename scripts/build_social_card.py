# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Build docs/social-preview.png, the 1280x640 card GitHub serves as
og:image once it is uploaded under Settings > General > Social preview.

There is no API for that upload, so the card is generated here, committed,
and put in place by hand. Rebuild it rather than editing the PNG.

Palette is the Studio dark theme (apps/studio/src/index.css): text
235 241 236, text-2 162 170 164, text-3 118 126 120, accent 92 178 130.
The backdrop is the real forest of the Explore console screenshot, cropped
to the canvas so no sidebar or filter panel rides into the frame.

    python scripts/build_social_card.py
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "social-preview.png")
W, H = 1280, 640

BG = (14, 17, 15)
TEXT = (255, 255, 255)
TEXT2 = (162, 170, 164)
TEXT3 = (118, 126, 120)
ACCENT = (92, 178, 130)
LINE = (44, 52, 45)

FONT_FILE = "/System/Library/Fonts/HelveticaNeue.ttc"
BOLD, MEDIUM, REGULAR = 1, 10, 0


def font(size: int, face: int = REGULAR) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_FILE, size, index=face)


def logo(size: int) -> Image.Image:
    """docs/logo.png as it ships: the app tile, white ground, green leaf.
    It carries its own contrast, so it is never recoloured here."""
    im = Image.open(os.path.join(ROOT, "docs", "logo.png")).convert("RGBA")
    return im.resize((size, size), Image.LANCZOS)


def backdrop() -> Image.Image:
    """The graph, dimmed, behind an elliptical vignette. The layout is
    centred, so the scrim has to be centred too: a left-to-right gradient
    would darken one half and leave the words fighting the other."""
    g = Image.open(os.path.join(ROOT, "docs/guide/assets/graph-sample.png")).convert("RGB")
    g = g.crop((292, 196, 1100, 712))  # the canvas alone, no console chrome
    g = g.resize((W, int(g.height * (W / g.width))), Image.LANCZOS)
    top = max((g.height - H) // 2, 0)
    g = g.crop((0, top, W, top + H))
    g = ImageEnhance.Brightness(g).enhance(0.62)
    g = ImageEnhance.Color(g).enhance(1.2)

    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    cx, cy, rx, ry = W / 2, H / 2, W * 0.60, H * 0.72
    for y in range(H):
        for x in range(0, W, 2):
            d = math.hypot((x - cx) / rx, (y - cy) / ry)
            t = max(0.0, min(1.0, (d - 0.42) / 0.58))
            md.rectangle([x, y, x + 1, y], fill=int(255 * (t * t * (3 - 2 * t))))

    card = Image.new("RGB", (W, H), BG)
    card.paste(g, (0, 0), mask)
    return card


def centred(d: ImageDraw.ImageDraw, text: str, y: int, f: ImageFont.FreeTypeFont, fill) -> None:
    d.text(((W - d.textlength(text, font=f)) / 2, y), text, font=f, fill=fill)


def wordmark(d: ImageDraw.ImageDraw, y: int, size: int) -> None:
    """Monkey in white, LLM in the accent."""
    f = font(size, BOLD)
    w_monkey = d.textlength("Monkey", font=f)
    x = W / 2 - (w_monkey + d.textlength("LLM", font=f)) / 2
    d.text((x, y), "Monkey", font=f, fill=TEXT)
    d.text((x + w_monkey, y), "LLM", font=f, fill=ACCENT)


def scoreline(d: ImageDraw.ImageDraw, y: int) -> None:
    """The benchmark, as the eye reads it: dead grey against the accent."""
    big, small, small_med = font(46, BOLD), font(26, REGULAR), font(26, MEDIUM)
    wa, wa2 = d.textlength("0/11", font=big), d.textlength("as top-k RAG", font=small)
    wb, wb2 = d.textlength("11/11", font=big), d.textlength("navigating", font=small_med)
    gap, bar = 14, 46
    x = W / 2 - (wa + gap + wa2 + bar + wb + gap + wb2) / 2

    d.text((x, y), "0/11", font=big, fill=TEXT3)
    d.text((x + wa + gap, y + 16), "as top-k RAG", font=small, fill=TEXT3)
    xb = x + wa + gap + wa2 + bar
    d.line([(xb - bar / 2, y + 6), (xb - bar / 2, y + 52)], fill=LINE, width=2)
    d.text((xb, y), "11/11", font=big, fill=ACCENT)
    d.text((xb + wb + gap, y + 16), "navigating", font=small_med, fill=ACCENT)


def build() -> Image.Image:
    card = backdrop()
    d = ImageDraw.Draw(card)

    mark = logo(128)
    card.paste(mark, ((W - mark.width) // 2, 52), mark)

    wordmark(d, 186, 88)
    centred(d, "A knowledge engine for AI agents.", 306, font(38, MEDIUM), TEXT)
    centred(d, "Your files become a markdown knowledge graph", 366, font(30), TEXT2)
    centred(d, "an agent navigates over MCP.", 406, font(30), TEXT2)
    scoreline(d, 490)
    centred(d, "same 12B local model, on questions needing three or more hops",
            558, font(22), TEXT3)
    return card


if __name__ == "__main__":
    build().save(OUT, "PNG", optimize=True)
    print(f"{OUT} ({os.path.getsize(OUT) // 1024} KB)")
