#!/usr/bin/env python3
"""Append Library CSS to the resources embedded in our pinned Kiwix binary.

Keep upstream layout and responsive rules rather than replacing the UI. This
build-time helper reads the ARM binary as data; it does not execute it. Fail the
image build if a future binary changes these resources so the theme is reviewed.
"""
import argparse
from pathlib import Path


RESOURCES = {
    "index.css": b"*,\n*::after,\n*::before {",
    "taskbar.css": b"#kiwixtoolbar {",
    "search_results.css": b"body{\nbackground-color: white;",
    "css/autoComplete.css": b".autoComplete_wrapper {",
}


def embedded_css(binary, prefix):
    if binary.count(prefix) != 1:
        raise ValueError(f"Expected one embedded stylesheet starting with {prefix!r}")
    # Resource arrays are not always NUL-terminated. End at the final CSS rule
    # before the next NUL, discarding any adjacent binary header bytes.
    payload = binary[binary.index(prefix):].split(b"\0", 1)[0]
    end = payload.rfind(b"}")
    css = payload[:end + 1].decode("utf-8")
    if end < 0 or not 500 < len(css) < 50000 or css.count("{") != css.count("}"):
        raise ValueError("Unrecognized embedded Kiwix stylesheet; review the new binary")
    return css


def build(binary_path, theme_path, output_path):
    binary = Path(binary_path).read_bytes()
    if b"KIWIX_SERVE_CUSTOMIZED_RESOURCES" not in binary:
        raise ValueError("This Kiwix binary does not support custom resources")
    theme = Path(theme_path).read_text(encoding="utf-8")
    output = Path(output_path)
    # Validate every resource before writing any output.
    sheets = {name: embedded_css(binary, prefix) for name, prefix in RESOURCES.items()}
    output.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, original in sheets.items():
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(original + "\n\n" + theme, encoding="utf-8")
        manifest.append(f"/skin/{name} text/css {destination.resolve()}")
    (output / "resources.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary")
    parser.add_argument("theme")
    parser.add_argument("output")
    args = parser.parse_args()
    build(args.binary, args.theme, args.output)
