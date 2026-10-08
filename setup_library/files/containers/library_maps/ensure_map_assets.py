#!/usr/bin/env python3
"""Populate missing offline map fonts/sprites before nginx starts.

The image keeps its seed outside /storage/maps so the USB bind mount cannot
hide it. Existing regular files, including customized assets, are preserved.
Copies are staged beside their destination then renamed, so an interrupted
startup does not leave a truncated asset that a later startup would skip.
No network access is needed. Run with optional SOURCE and DESTINATION paths
to exercise this helper against temporary directories.
"""

import argparse
import os
from pathlib import Path
import shutil
import sys
import tempfile

DEFAULT_SOURCE = Path("/opt/library_maps/basemaps-assets")
DEFAULT_DESTINATION = Path("/storage/maps/basemaps-assets")


def ensure_directory(path):
    """Create missing directory components, refusing symlinks or file conflicts."""
    if path.is_symlink():
        raise ValueError(f"Asset directory must not be a symlink: {path}")
    if path.exists():
        if not path.is_dir():
            raise ValueError(f"Asset directory is a file: {path}")
        # Check ancestors even when this directory already exists.
        if path != path.parent:
            ensure_directory(path.parent)
        return
    ensure_directory(path.parent)
    path.mkdir(exist_ok=True)


def install_missing(source=DEFAULT_SOURCE, destination=DEFAULT_DESTINATION):
    """Return (copied, preserved) after installing absent bundled files.

    A complete read-only destination is supported because existing files are
    never opened for writing. If anything is missing on a read-only mount, let
    the error propagate so startup can explain how to correct the volume mode.
    Empty or corrupt existing files are preserved too; this is not an updater.
    """
    source, destination = Path(source).absolute(), Path(destination).absolute()
    if not source.is_dir():
        raise ValueError(f"Bundled map assets are missing: {source}")
    files = sorted(source.rglob("*"))
    if not any(path.is_file() for path in files):
        raise ValueError(f"Bundled map assets are empty: {source}")
    copied = preserved = 0
    for bundled in files:
        if bundled.is_symlink():
            raise ValueError(f"Bundled asset must not be a symlink: {bundled}")
        if bundled.is_dir():
            continue
        target = destination / bundled.relative_to(source)
        ensure_directory(target.parent)
        if target.is_symlink():
            raise ValueError(f"Asset file must not be a symlink: {target}")
        if target.exists():
            if not target.is_file():
                raise ValueError(f"Asset filename is a directory: {target}")
            preserved += 1
            continue
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".map-asset-", dir=target.parent,
                                             delete=False) as output:
                temporary = Path(output.name)
                with bundled.open("rb") as incoming:
                    shutil.copyfileobj(incoming, output)
                output.flush()
                os.fsync(output.fileno())
            temporary.chmod(0o644)  # nginx workers must be able to read the seed.
            # Another startup/manual copy may have filled the gap while copying.
            if target.exists() or target.is_symlink():
                raise ValueError(f"Asset appeared during startup; retry: {target}")
            temporary.rename(target)
            copied += 1
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return copied, preserved


def main():
    """Run the startup check, returning a nonzero status on incomplete setup."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("destination", nargs="?", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()
    try:
        copied, preserved = install_missing(args.source, args.destination)
    except (OSError, ValueError) as exc:
        print(f"Map asset setup failed: {exc}\n"
              "Mount /storage/maps read-write to install missing bundled fonts/sprites, "
              "and check available space and directory permissions.", file=sys.stderr)
        return 1
    print(f"Map assets ready: copied {copied} missing files; preserved {preserved} existing files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
