"""Check missing-asset startup repair with temporary directories, no network."""

import errno
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ensure_map_assets import install_missing


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "seed"
        self.destination = self.root / "maps" / "basemaps-assets"
        for name, data in [("fonts/Noto Sans Regular/0-255.pbf", b"font"),
                           ("sprites/v4/light.json", b"{}"),
                           ("sprites/v4/light.png", b"sprite"),
                           ("fonts/OFL.txt", b"license")]:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def test_empty_drive_gets_every_asset_and_notice(self):
        self.assertEqual(install_missing(self.source, self.destination), (4, 0))
        for path in self.source.rglob("*"):
            if path.is_file():
                target = self.destination / path.relative_to(self.source)
                self.assertEqual(target.read_bytes(), path.read_bytes())
                self.assertTrue(target.stat().st_mode & 0o004)

    def test_restart_preserves_custom_files_and_restores_only_missing(self):
        install_missing(self.source, self.destination)
        custom = self.destination / "sprites/v4/light.json"
        custom.write_bytes(b'{"custom": true}')
        missing = self.destination / "sprites/v4/light.png"
        missing.unlink()
        extra = self.destination / "extra.txt"
        extra.write_bytes(b"keep")
        self.assertEqual(install_missing(self.source, self.destination), (1, 3))
        self.assertEqual(custom.read_bytes(), b'{"custom": true}')
        self.assertEqual(extra.read_bytes(), b"keep")
        self.assertEqual(missing.read_bytes(), b"sprite")

    def test_complete_destination_requires_no_writes(self):
        install_missing(self.source, self.destination)
        with patch("ensure_map_assets.tempfile.NamedTemporaryFile", side_effect=AssertionError("unexpected write")), \
                patch.object(Path, "mkdir", side_effect=AssertionError("unexpected mkdir")):
            self.assertEqual(install_missing(self.source, self.destination), (0, 4))

    def test_copy_failure_leaves_no_partial_asset(self):
        def fail(source, output):
            output.write(b"partial")
            raise OSError(errno.ENOSPC, "no space")
        with patch("ensure_map_assets.shutil.copyfileobj", side_effect=fail), self.assertRaises(OSError):
            install_missing(self.source, self.destination)
        self.assertFalse(any(path.is_file() for path in self.destination.rglob("*")))
        self.assertEqual(install_missing(self.source, self.destination), (4, 0))

    def test_symlink_destination_cannot_write_outside_maps(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.destination.parent.mkdir(parents=True)
        self.destination.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            install_missing(self.source, self.destination)
        self.assertEqual(list(outside.iterdir()), [])

    def test_filename_conflict_is_reported(self):
        (self.destination / "fonts/OFL.txt").mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "filename is a directory"):
            install_missing(self.source, self.destination)

    def test_empty_or_missing_seed_is_reported(self):
        for source in [self.root / "missing", self.root / "empty"]:
            if source.name == "empty":
                source.mkdir()
            with self.assertRaises(ValueError):
                install_missing(source, self.destination)

    def test_bundled_assets_match_manifest_and_viewer_paths(self):
        seed = Path(__file__).resolve().parents[1] / "basemaps-assets"
        names = set()
        for line in (seed / "SHA256SUMS").read_text().splitlines():
            digest, relative = line.split("  ", 1)
            names.add(relative)
            self.assertEqual(hashlib.sha256((seed / relative).read_bytes()).hexdigest(), digest, relative)
        self.assertEqual(names, {str(path.relative_to(seed)) for path in seed.rglob("*")
                                 if path.is_file() and path.name != "SHA256SUMS"})
        self.assertIn("fonts/Noto Sans Regular/0-255.pbf", names)
        self.assertIn("sprites/v4/light.json", names)
        self.assertIn("sprites/v4/light@2x.png", names)


if __name__ == "__main__":
    unittest.main()
