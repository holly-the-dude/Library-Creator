#!/usr/bin/env python3
"""
Generate a status splash image using blank.jpg and a custom message color.
Prompts for the output filename, message, and a named or six-digit hex color.
Relative output paths are saved alongside this script.

Run: python3 make_image.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
BLANK = os.path.join(HERE, "blank.jpg")

LBLUE = (187, 239, 246)
GREEN = (0, 230, 0)
RED = (210, 0, 0)
WHITE = (255, 255, 255)

COLORS = {
    "green": GREEN,
    "red": (255, 0, 0),
    "blue": (0, 0, 255),
    "light blue": LBLUE,
    "white": WHITE,
    "yellow": (255, 255, 0),
    "orange": (255, 165, 0),
    "purple": (128, 0, 128),
    "pink": (255, 192, 203),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "gray": (128, 128, 128),
    "black": (0, 0, 0),
}

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

    # Title: top-left, bold mono, wrapped to fit width with a 20px margin.
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
    img.save(out, quality=90)
    print(f"wrote {out}  ({title!r}{', progress' if progress else ''})")


def prompt_required(prompt):
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("Please enter a value.")


def prompt_color():
    print("Available text colors:")
    for name, rgb in COLORS.items():
        print(f"  {name:10} #{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}")
    while True:
        value = input("Text color (name or hex, e.g. FF0000) [green]: ").strip().lower()
        if not value:
            return GREEN
        if value in COLORS:
            return COLORS[value]
        hex_value = value.removeprefix("#")
        if len(hex_value) == 6 and all(c in "0123456789abcdef" for c in hex_value):
            return tuple(int(hex_value[i:i + 2], 16) for i in (0, 2, 4))
        print("Choose a listed color or enter six hex digits, such as FF0000 or #FF0000.")


def main():
    while True:
        name = prompt_required("Output filename (.jpg or .png): ")
        extension = os.path.splitext(name)[1].lower()
        if not extension:
            name += ".jpg"
            break
        if extension in (".jpg", ".jpeg", ".png"):
            break
        print("Use a .jpg, .jpeg, or .png filename.")
    title = prompt_required("Message to show: ")
    color = prompt_color()
    make(name, title, color=color)


if __name__ == "__main__":
    main()
