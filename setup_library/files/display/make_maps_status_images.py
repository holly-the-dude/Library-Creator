#!/usr/bin/env python3
"""
Generate 480x320 status splash images for the maps + routing startup, matching
the existing display style:
  - black background with the LIBRARY logo in the bottom-left quarter (blank.jpg)
  - bright green bold-monospace title text at top-left
  - optional red "progress" pill in the middle (used by the existing
    start_06/07 webserver splashes)

Run from setup_library/files/display/:  python3 make_maps_status_images.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
BLANK = os.path.join(HERE, "blank.jpg")

GREEN = (0, 230, 0)
RED = (210, 0, 0)
WHITE = (255, 255, 255)

FONT_CANDIDATES = [
    "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/liberation-mono/LiberationMono-Bold.ttf",
]


def load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def wrap_title(draw, text, font, max_width):
    """Greedy word-wrap so long titles fit the 480px width with a margin."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def make(name, title, progress=False, color=GREEN):
    img = Image.open(BLANK).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Title: top-left, bold green mono, wrapped to fit width with a 20px margin.
    size = 40
    font = load_font(size)
    margin = 20
    max_w = img.width - 2 * margin
    # Shrink font until the longest word fits, then wrap.
    while size > 20:
        font = load_font(size)
        if max(draw.textlength(w, font=font) for w in title.split()) <= max_w:
            break
        size -= 2
    lines = wrap_title(draw, title, font, max_w)

    y = 16
    for line in lines:
        draw.text((margin, y), line, font=font, fill=color)
        y += size + 6

    # Optional red progress pill in the middle (mirrors the webserver splashes).
    if progress:
        px0, py0, px1, py1 = 40, 150, 170, 182
        r = (py1 - py0) // 2
        draw.rounded_rectangle([px0, py0, px1, py1], radius=r, fill=RED,
                               outline=WHITE, width=3)

    out = os.path.join(HERE, name)
    img.save(out, "JPEG", quality=90)
    print(f"wrote {name}  ({title!r}{', progress' if progress else ''})")


# Maps + routing startup sequence. Numbered to sit alongside the existing
# start_0X_* sequence (webserver is 06/07), so maps/routing use 08/09.
make("start_08_starting_maps.jpg",   "Starting Maps")
make("start_08_maps_started.jpg",    "Maps Started")
make("start_09_building_routing.jpg","Building Routing", progress=True)
make("start_09_routing_ready.jpg",   "Routing Ready")
make("start_09_routing_off.jpg",     "Maps Ready No Routing", color=GREEN)
make("start_09_routing_failed.jpg",  "Routing Failed", color=RED)
