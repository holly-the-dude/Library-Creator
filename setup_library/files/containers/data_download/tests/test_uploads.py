"""Upload integration checks using disposable storage and loopback HTTP only."""
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import uploads


def archive(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in entries:
            bundle.writestr(name, data)
    return buffer.getvalue()


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = app.Storage(self.root, require_mount=False, reserve=0)
        self.application = app.Application(self.storage)

    def upload(self, category, path, data=b"sample"):
        return self.application.upload(io.BytesIO(data), len(data), category, path)

    def assert_clean(self):
        self.assertFalse(self.application.upload_active)
        scratch = self.root / ".data_download/uploads"
        self.assertEqual(list(scratch.iterdir()) if scratch.exists() else [], [])

    def test_destinations_folder_structure_unicode_and_empty_files_offline(self):
        for category, directory in uploads.DESTINATIONS.items():
            for filename, data in [("Album/Café & song.mp3", b"music"), ("empty", b"")]:
                with self.subTest(category=category, filename=filename):
                    self.upload(category, filename, data)
                    self.assertEqual((self.root / directory / filename).read_bytes(), data)
        self.assertTrue(self.application.snapshot()["storage"]["ready"])
        self.assert_clean()

    def test_zip_extracts_all_files_in_destination_and_removes_archive(self):
        data = archive([("album/song.mp3", b"song"), ("notes.txt", b"notes"), ("empty/", b"")])
        for category, directory in uploads.DESTINATIONS.items():
            with self.subTest(category=category):
                result = self.upload(category, "Chosen/collection.ZIP", data)
                target = self.root / directory / "Chosen"
                self.assertEqual((target / "album/song.mp3").read_bytes(), b"song")
                self.assertEqual((target / "notes.txt").read_bytes(), b"notes")
                self.assertTrue((target / "empty").is_dir())
                self.assertFalse((target / "collection.ZIP").exists())
                self.assertEqual(result["files"], 2)
                self.assertTrue(result["extracted"])
        self.assert_clean()

    def test_epub_and_nested_archives_remain_files(self):
        data = archive([("inside.txt", b"text")])
        self.upload("ebooks", "book.epub", data)
        self.assertEqual((self.root / "calibre/put_new_books_here/book.epub").read_bytes(), data)
        self.upload("data", "outer.zip", archive([("inner.zip", data)]))
        self.assertEqual((self.root / "library/inner.zip").read_bytes(), data)

    def test_invalid_categories_and_unsafe_upload_paths(self):
        for path in ["../escape", "/absolute", "x/../../escape", "x\\escape", "C:drive", "a//b", "./a", "a\x00b", "a/", ""]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.upload("data", path)
        with self.assertRaises(ValueError):
            self.upload("unknown", "test")
        self.assertEqual(list(self.root.iterdir()), [])
        self.assert_clean()

    def test_zip_traversal_symlinks_special_files_and_duplicates_rejected(self):
        symlink = zipfile.ZipInfo("link")
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        fifo = zipfile.ZipInfo("fifo")
        fifo.external_attr = (stat.S_IFIFO | 0o600) << 16
        cases = [[("../outside", b"bad")], [("/absolute", b"bad")],
                 [("folder\\escape", b"bad")], [(symlink, b"target")], [(fifo, b"")],
                 [("A.txt", b"a"), ("a.txt", b"b")]]
        for entries in cases:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                self.upload("data", "bad.zip", archive([("safe.txt", b"ok")] + entries))
            self.assertFalse((self.root / "library").exists())
            self.assert_clean()

    def test_existing_file_and_zip_conflict_preserve_content(self):
        self.upload("data", "keep.txt", b"original")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.upload("data", "keep.txt", b"replacement")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.upload("data", "bundle.zip", archive([("new.txt", b"new"), ("keep.txt", b"bad")]))
        self.assertEqual((self.root / "library/keep.txt").read_bytes(), b"original")
        self.assertFalse((self.root / "library/new.txt").exists())
        self.assert_clean()

    def test_existing_symlink_is_not_followed(self):
        (self.root / "outside").mkdir()
        (self.root / "music").symlink_to(self.root / "outside", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.upload("music", "song.mp3")
        (self.root / "library").mkdir()
        (self.root / "library/link").symlink_to(self.root / "outside", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.upload("data", "bundle.zip", archive([("link/escape", b"bad")]))
        self.assertEqual(list((self.root / "outside").iterdir()), [])
        self.assert_clean()

    def test_interrupted_and_corrupt_uploads_are_cleaned_up(self):
        with self.assertRaisesRegex(ValueError, "interrupted"):
            self.application.upload(io.BytesIO(b"short"), 100, "data", "file")
        corrupt = archive([("test", b"UNIQUE_PAYLOAD")]).replace(b"UNIQUE_PAYLOAD", b"CORRUPT_BYTES!")
        for data in [b"not a ZIP", corrupt]:
            with self.assertRaises(ValueError):
                self.upload("data", "bad.zip", data)
        self.assertFalse((self.root / "library").exists())
        self.assert_clean()

    def test_space_failure_during_publication_rolls_back_batch(self):
        original_copy = uploads.copy_stream

        def failing_copy(source, output, storage):
            original_copy(source, output, storage)
            if str(output.name).endswith("library/b.txt"):
                raise OSError("No space left on device")

        with patch.object(uploads, "copy_stream", side_effect=failing_copy):
            with self.assertRaises(OSError):
                self.upload("data", "batch.zip", archive([("a.txt", b"a"), ("b.txt", b"b")]))
        self.assertFalse((self.root / "library").exists())
        self.assert_clean()

    def test_upload_size_and_expanded_size_check_free_space(self):
        with patch.object(self.storage, "space", side_effect=ValueError("Not enough space")):
            with self.assertRaisesRegex(ValueError, "Not enough"):
                self.upload("music", "file")
        data = archive([("large.txt", b"x" * 1000)])
        with patch.object(self.storage, "space", side_effect=[None, None, ValueError("Not enough expanded space")]):
            with self.assertRaisesRegex(ValueError, "expanded space"):
                self.upload("data", "large.zip", data)
        self.assertFalse((self.root / "library").exists())
        self.assert_clean()

    def test_active_upload_excludes_restart_and_other_uploads(self):
        application = self.application

        class CheckedStream(io.BytesIO):
            def read(inner, size):
                self.assertTrue(application.snapshot()["upload_active"])
                with self.assertRaisesRegex(ValueError, "Wait for uploads"):
                    application.restart()
                with self.assertRaisesRegex(ValueError, "Another upload"):
                    self.upload("data", "second.txt")
                return super().read(size)

        application.upload(CheckedStream(b"abc"), 3, "data", "first.txt")
        self.assert_clean()
        application.restart_requested = True
        with self.assertRaisesRegex(ValueError, "restarting"):
            self.upload("data", "after.txt")


class UploadHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.application = app.Application(app.Storage(self.temp.name, require_mount=False, reserve=0))
        self.server = app.make_server(self.application, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}/api/upload?"

    def request(self, query, data=b"text", token=True):
        headers = {"Content-Type": "application/octet-stream"}
        if token:
            headers["X-Library-Token"] = self.application.token
        return Request(self.base + query, data=data, headers=headers)

    def test_streamed_uploads_larger_than_json_limit_and_zero_bytes(self):
        for path, data in [("Folder/café #?.txt", b"x" * 70000), ("empty.txt", b"")]:
            request = self.request(urlencode({"category": "data", "path": path}), data)
            with urlopen(request) as response:
                self.assertEqual(response.status, 201)
                self.assertTrue(json.load(response)["ok"])
            self.assertEqual((Path(self.temp.name) / "library" / path).read_bytes(), data)

    def test_token_validation_and_error_responses(self):
        for query, data, token, status in [
                ("category=music&path=file", b"x", False, 403),
                ("category=data&path=../outside", b"x", True, 400),
                ("category=data&path=bad.zip", b"not a zip", True, 400),
                ("category=invalid&path=file", b"x", True, 400),
                ("category=data&path=a&path=b", b"x", True, 400),
                ("category=data", b"x", True, 400)]:
            with self.subTest(query=query), self.assertRaises(HTTPError) as error:
                urlopen(self.request(query, data, token))
            self.assertEqual(error.exception.code, status)
            self.assertIn("error", json.load(error.exception))


if __name__ == "__main__":
    unittest.main()
