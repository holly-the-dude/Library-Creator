"""Validate resource generation against the shipped ARM binary without running it."""
import importlib.util
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_theme", ROOT / "build_theme.py")
theme_builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(theme_builder)


class ThemeBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tarfile.open(ROOT / "kiwix-tools_linux-aarch64-3.5.0-1.tar.gz") as archive:
            member = next(item for item in archive.getmembers() if item.name.endswith("/kiwix-serve"))
            cls.binary = archive.extractfile(member).read()

    def test_bundled_binary_generates_all_resources_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "kiwix-serve"
            binary.write_bytes(self.binary)
            output = root / "skin"
            theme_builder.build(binary, ROOT / "library-theme.css", output)
            manifest = (output / "resources.txt").read_text().splitlines()
            self.assertEqual(len(manifest), 4)
            for line, (name, prefix) in zip(manifest, theme_builder.RESOURCES.items()):
                url, mime, path = line.split()
                self.assertEqual(url, "/skin/" + name)
                self.assertEqual(mime, "text/css")
                self.assertEqual(Path(path), output / name)
                css = Path(path).read_text()
                self.assertTrue(css.startswith(prefix.decode()))
                self.assertTrue(css.endswith((ROOT / "library-theme.css").read_text()))
                self.assertEqual(css.count("{"), css.count("}"))

    def test_changed_binary_fails_before_writing_partial_skin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "kiwix-serve"
            binary.write_bytes(self.binary.replace(b"#kiwixtoolbar {", b"#changedbar  {"))
            with self.assertRaisesRegex(ValueError, "Expected one embedded stylesheet"):
                theme_builder.build(binary, ROOT / "library-theme.css", root / "skin")
            self.assertFalse((root / "skin").exists())

    def test_binary_without_custom_resource_support_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "kiwix-serve"
            binary.write_bytes(b"unsupported version")
            with self.assertRaisesRegex(ValueError, "does not support custom resources"):
                theme_builder.build(binary, ROOT / "library-theme.css", root / "skin")
            self.assertFalse((root / "skin").exists())


if __name__ == "__main__":
    unittest.main()
