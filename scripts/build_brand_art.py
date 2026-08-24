# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Build the two brand images, from one palette and one set of numbers.

  docs/banner.png          2000x760, the README hero: wordmark, tagline and
                           the stat strip.
  docs/social-preview.png  1280x640, what GitHub serves as og:image once it
                           is uploaded under Settings > General > Social
                           preview. There is no API for that upload, so the
                           card is generated here, committed, and put in
                           place by hand.

Rebuild them rather than editing the PNGs.

Every figure in the strip is quoted, and STATS names where each one comes
from. A number that cannot be pointed at does not go on a banner: the README
carried 0.58x for months after the paper had corrected it to 0.66x.

Palette is the Studio dark theme (apps/studio/src/index.css): text
235 241 236, text-2 162 170 164, text-3 118 126 120, accent 92 178 130.
The backdrop is the real forest of the Explore console screenshot, cropped
to the canvas so no sidebar or filter panel rides into the frame.

    python scripts/build_brand_art.py
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARD = os.path.join(ROOT, "docs", "social-preview.png")
BANNER = os.path.join(ROOT, "docs", "banner.png")

BG = (14, 17, 15)
TEXT = (255, 255, 255)
TEXT2 = (162, 170, 164)
TEXT3 = (118, 126, 120)
ACCENT = (92, 178, 130)
RULE = (58, 66, 59)

FONT_FILE = "/System/Library/Fonts/HelveticaNeue.ttc"
BOLD, MEDIUM, REGULAR = 1, 10, 0

TAGLINE = "A knowledge engine for AI agents."
SUBLINE = "Your files become a markdown knowledge graph an agent navigates over MCP."
PILL = "Apache-2.0  ·  pip install monkeyllm"

# value, label, note, source
STATS = [
    ("11/11", "Multi-hop QA", "same 12B model, 0/11 as top-k RAG",
     "paper §5, abstract"),
    ("1.3 ms", "Entry search", "p95, recall@5 = 1.0, no embedder",
     "paper §5.1, BM25 scent-weighted row"),
    ("0.66×", "Token cost", "per correct answer vs iterative RAG",
     "paper §5, 1433 against 2175"),
    ("1,309", "Tests green", "the spec is the contract",
     "pytest --collect-only at this commit"),
]


def font(size: int, face: int = REGULAR) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_FILE, size, index=face)


def logo(size: int) -> Image.Image:
    """docs/logo.png as it ships: the app tile, white ground, green leaf.
    It carries its own contrast, so it is never recoloured here."""
    im = Image.open(os.path.join(ROOT, "docs", "logo.png")).convert("RGBA")
    return im.resize((size, size), Image.LANCZOS)


def backdrop(w: int, h: int) -> Image.Image:
    """The graph, dimmed, behind an elliptical vignette. Both layouts are
    centred, so the scrim has to be centred too: a left-to-right gradient
    would darken one half and leave the words fighting the other."""
    g = Image.open(os.path.join(ROOT, "docs/guide/assets/graph-sample.png")).convert("RGB")
    g = g.crop((292, 196, 1100, 712))  # the canvas alone, no console chrome
    scale = max(w / g.width, h / g.height)
    g = g.resize((int(g.width * scale) + 1, int(g.height * scale) + 1), Image.LANCZOS)
    g = g.crop(((g.width - w) // 2, (g.height - h) // 2,
                (g.width - w) // 2 + w, (g.height - h) // 2 + h))
    g = ImageEnhance.Brightness(g).enhance(0.62)
    g = ImageEnhance.Color(g).enhance(1.2)

    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    cx, cy, rx, ry = w / 2, h / 2, w * 0.60, h * 0.72
    for y in range(h):
        for x in range(0, w, 2):
            d = math.hypot((x - cx) / rx, (y - cy) / ry)
            t = max(0.0, min(1.0, (d - 0.42) / 0.58))
            md.rectangle([x, y, x + 1, y], fill=int(255 * (t * t * (3 - 2 * t))))

    card = Image.new("RGB", (w, h), BG)
    card.paste(g, (0, 0), mask)
    return card


def centred(d, text, y, f, fill, w):
    d.text(((w - d.textlength(text, font=f)) / 2, y), text, font=f, fill=fill)


def wordmark(d, y, size, w):
    """Monkey in white, LLM in the accent."""
    f = font(size, BOLD)
    w_monkey = d.textlength("Monkey", font=f)
    x = w / 2 - (w_monkey + d.textlength("LLM", font=f)) / 2
    d.text((x, y), "Monkey", font=f, fill=TEXT)
    d.text((x + w_monkey, y), "LLM", font=f, fill=ACCENT)


def pill(d, y, w, text, size=26):
    """The badge under the tagline: a rounded outline, never a filled chip.
    A filled one competes with the accent that the numbers need."""
    f = font(size, MEDIUM)
    tw = d.textlength(text, font=f)
    pad_x, h = 26, size + 26
    x0 = w / 2 - (tw + 2 * pad_x) / 2
    d.rounded_rectangle([x0, y, x0 + tw + 2 * pad_x, y + h],
                        radius=h / 2, outline=RULE, width=2)
    d.text((x0 + pad_x, y + (h - size) / 2 - 3), text, font=f, fill=TEXT2)


def strip(d, top, w, margin, value_size=76, label_size=28, note_size=21):
    """The stat strip: one column per figure, hairline between them."""
    col = (w - 2 * margin) / len(STATS)
    f_v, f_l, f_n = font(value_size, BOLD), font(label_size, BOLD), font(note_size, REGULAR)
    for i, (value, label, note, _src) in enumerate(STATS):
        cx = margin + col * (i + 0.5)
        d.text((cx - d.textlength(value, font=f_v) / 2, top), value, font=f_v, fill=ACCENT)
        y = top + value_size + 18
        d.text((cx - d.textlength(label, font=f_l) / 2, y), label, font=f_l, fill=TEXT)
        y += label_size + 12
        d.text((cx - d.textlength(note, font=f_n) / 2, y), note, font=f_n, fill=TEXT3)
        if i:
            x = margin + col * i
            d.line([(x, top - 4), (x, y + note_size + 6)], fill=RULE, width=2)


def build_banner():
    w, h = 2000, 760
    im = backdrop(w, h)
    d = ImageDraw.Draw(im)

    mark = logo(104)
    im.paste(mark, ((w - mark.width) // 2, 38), mark)
    wordmark(d, 158, 104, w)
    centred(d, TAGLINE, 300, font(40, MEDIUM), TEXT, w)
    centred(d, SUBLINE, 356, font(30), TEXT2, w)
    pill(d, 420, w, PILL)

    d.line([(150, 512), (w - 150, 512)], fill=RULE, width=2)
    strip(d, 548, w, 150)
    return im


def build_card():
    """The card is read small, in a timeline. It carries the one number that
    survives being small, not the strip."""
    w, h = 1280, 640
    im = backdrop(w, h)
    d = ImageDraw.Draw(im)

    mark = logo(128)
    im.paste(mark, ((w - mark.width) // 2, 52), mark)
    wordmark(d, 186, 88, w)
    centred(d, TAGLINE, 306, font(38, MEDIUM), TEXT, w)
    centred(d, "Your files become a markdown knowledge graph", 366, font(30), TEXT2, w)
    centred(d, "an agent navigates over MCP.", 406, font(30), TEXT2, w)

    big, small, small_med = font(46, BOLD), font(26, REGULAR), font(26, MEDIUM)
    wa, wa2 = d.textlength("0/11", font=big), d.textlength("as top-k RAG", font=small)
    wb, wb2 = d.textlength("11/11", font=big), d.textlength("navigating", font=small_med)
    gap, bar, y = 14, 46, 490
    x = w / 2 - (wa + gap + wa2 + bar + wb + gap + wb2) / 2
    d.text((x, y), "0/11", font=big, fill=TEXT3)
    d.text((x + wa + gap, y + 16), "as top-k RAG", font=small, fill=TEXT3)
    xb = x + wa + gap + wa2 + bar
    d.line([(xb - bar / 2, y + 6), (xb - bar / 2, y + 52)], fill=RULE, width=2)
    d.text((xb, y), "11/11", font=big, fill=ACCENT)
    d.text((xb + wb + gap, y + 16), "navigating", font=small_med, fill=ACCENT)
    centred(d, "same 12B local model, on questions needing three or more hops",
            558, font(22), TEXT3, w)
    return im


if __name__ == "__main__":
    for path, image in ((BANNER, build_banner()), (CARD, build_card())):
        image.save(path, "PNG", optimize=True)
        print(f"{path} ({os.path.getsize(path) // 1024} KB, {image.size[0]}x{image.size[1]})")
