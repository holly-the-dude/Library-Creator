"""Offline regression tests for the data_download Python programs.

Run from the container directory with:
    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v

Source responses and connectivity checks are mocked. Storage fixtures use
temporary directories, and HTTP tests bind ephemeral ports on 127.0.0.1.
Nothing downloads external content or writes to the real /Library drive.
See ../docs/TESTING.md for coverage, prerequisites, and manual Pi checks.
"""

import hashlib
import io
import json
import stat
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import sources


class Response(io.BytesIO):
    """In-memory urllib response stand-in with status/headers and context support."""

    def __init__(self, body, status=200, headers=None):
        """Wrap fixture bytes with the HTTP metadata needed by the downloader."""
        super().__init__(body)
        self.status = status
        self.headers = headers or {}


class DiscoveryTests(unittest.TestCase):
    """Check connectivity heuristics and catalog parsing without remote requests."""
    def test_internet_probe_tries_another_host_when_one_is_down(self):
        response = Response(b"")
        response.geturl = lambda: "https://dumps.wikimedia.org/"
        with patch.object(sources, "urlopen", side_effect=[URLError("offline"), response]) as request:
            self.assertTrue(sources.internet_available())
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args.args[0].get_method(), "HEAD")
        self.assertEqual(request.call_args.kwargs["timeout"], 5)

    def test_internet_probe_reports_offline_when_all_hosts_fail(self):
        with patch.object(sources, "urlopen", side_effect=URLError("DNS failed")) as request:
            self.assertFalse(sources.internet_available())
        self.assertEqual(request.call_count, 4)

    def test_server_rate_limit_still_means_internet_is_available(self):
        error = HTTPError("https://github.com/", 429, "Rate limited", {}, io.BytesIO())
        with patch.object(sources, "urlopen", side_effect=error):
            self.assertTrue(sources.internet_available())

    def test_captive_portal_redirect_is_not_internet_access(self):
        def portal(*args, **kwargs):
            response = Response(b"")
            response.geturl = lambda: "https://login.example/"
            return response
        with patch.object(sources, "urlopen", side_effect=portal):
            self.assertFalse(sources.internet_available())

    def test_wikipedia_exact_sizes_relative_links_and_no_non_zims(self):
        rows = sources.parse_wiki('''<pre><a href="../">../</a>
<a href="wikipedia_en_all_2026-09.zim">Wikipedia</a> 06-Oct-2026 05:22 105478509329
<a href="wikipedia_fr_all_2026-08.zim">French</a> 21-Aug-2026 05:22 1234
<a href="checksum.txt">checksum.txt</a>
<a href="https://example.org/evil.zim">outside</a></pre>''')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["size"], 105478509329)
        self.assertEqual(rows[1]["size"], 1234)
        self.assertEqual(rows[0]["destination"], "wiki/wikipedia_en_all_2026-09.zim")

    def test_survivor_only_category_links(self):
        categories = sources.category_links('''
<a href="/index.php/library-accounting/">Accounting</a>
<a href="/index.php/store/">Store</a>
<a href="https://evil.example/index.php/library-example/">Wrong host</a>''')
        self.assertEqual(list(categories.values()), ["Accounting"])

    def test_survivor_zip_case_and_malformed_unquoted_anchor(self):
        rows = sources.parse_survivor('''
<a href="/library/book.pdf">PDF</a>
<td><a href=https://www.survivorlibrary.com/library/Accounting.ZIP target=blank download>ZIP 253 mb</td>
<a href="/library/Accounting.ZIP">Duplicate</a>
<a href="https://evil.example/library/evil.zip">Wrong host</a>''', sources.SURVIVOR_URL, "Accounting")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["destination"], "library/Accounting")
        self.assertIsNone(rows[0]["size"])  # Rounded HTML MB values are not exact.

    def test_lfs_size_checksum_and_media_url(self):
        pointer = "version https://git-lfs.github.com/spec/v1\noid sha256:" + "a" * 64 + "\nsize 12345678\n"
        with patch.object(sources, "fetch", return_value=pointer):
            row = sources.map_item({"name": "state.pmtiles", "size": 133,
                                   "download_url": "https://raw.githubusercontent.com/owner/maps/main/pmtiles/state.pmtiles"})
        self.assertEqual(row["size"], 12345678)
        self.assertEqual(row["sha256"], "a" * 64)
        self.assertIn("media.githubusercontent.com/media/", row["url"])

    def test_unsafe_filenames(self):
        for name in ["../bad", "a\\b", ".hidden", "evil\x00", ".."]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                sources.safe_name(name)


class StorageTests(unittest.TestCase):
    """Exercise storage, transfers, extraction, queues, and connection lifecycle."""

    def setUp(self):
        """Create isolated storage with no reserve and a fresh cancellation event."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = app.Storage(self.root, require_mount=False, reserve=0)
        self.event = threading.Event()
        self.progress = lambda **kwargs: None

    def test_mount_required_and_missing_root_does_not_get_created(self):
        self.assertFalse(app.Storage(self.root).status()["ready"])
        missing = self.root / "missing"
        self.assertFalse(app.Storage(missing).status()["ready"])
        self.assertFalse(missing.exists())

    def test_paths_cannot_escape_mount_or_follow_symlinks(self):
        (self.root / "wiki").symlink_to("/tmp", target_is_directory=True)
        for relative in ["../outside", "/tmp/file", "wiki/file.zim"]:
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                self.storage.path(relative)

    def test_reserve_prevents_writes(self):
        with patch.object(app.shutil, "disk_usage", return_value=type("Usage", (), {"free": 100})()):
            self.storage.reserve = 50
            self.storage.space(50)
            with self.assertRaises(ValueError):
                self.storage.space(51)

    def row(self, data=b"PMTiles\x03example"):
        """Build a synthetic map row with the fixture's exact size and checksum."""
        return sources.item("maps", "https://example.org/state.pmtiles", len(data),
                            sha256=hashlib.sha256(data).hexdigest())

    def test_download_and_checksum(self):
        data = b"PMTiles\x03example"
        part = self.root / "test.part"
        with patch.object(sources, "open_url", return_value=Response(data, headers={"Content-Length": str(len(data)), "ETag": '"v1"'})):
            app.stream_download(self.row(data), part, self.storage, self.event, self.progress)
        app.verify(self.row(data), part, self.event)
        self.assertEqual(part.read_bytes(), data)

    def test_resume_uses_range_and_if_range(self):
        data = b"PMTiles\x03example"
        row = self.row(data)
        part = self.root / "test.part"
        part.write_bytes(data[:8])
        app.atomic_json(part.with_suffix(".json"), {"url": row["url"], "etag": '"v1"'})
        headers = {"Content-Range": f"bytes 8-{len(data) - 1}/{len(data)}", "ETag": '"v1"'}
        with patch.object(sources, "open_url", return_value=Response(data[8:], 206, headers)) as request:
            app.stream_download(row, part, self.storage, self.event, self.progress)
        self.assertEqual(request.call_args.args[1], {"Range": "bytes=8-", "If-Range": '"v1"'})
        self.assertEqual(part.read_bytes(), data)

    def test_range_ignored_restarts_without_appending(self):
        data = b"PMTiles\x03example"
        row = self.row(data)
        part = self.root / "test.part"
        part.write_bytes(b"old partial")
        app.atomic_json(part.with_suffix(".json"), {"url": row["url"], "etag": '"old"'})
        with patch.object(sources, "open_url", return_value=Response(data, headers={"Content-Length": str(len(data))})):
            app.stream_download(row, part, self.storage, self.event, self.progress)
        self.assertEqual(part.read_bytes(), data)

    def test_finished_zip_retry_reuses_archive_after_space_failure(self):
        row = sources.item("survivor", "https://www.survivorlibrary.com/library/Test.ZIP")
        part = self.root / "test.part"
        part.write_bytes(b"completed archive")
        app.atomic_json(part.with_suffix(".json"), {"url": row["url"], "etag": '"v1"', "total": part.stat().st_size})
        with patch.object(sources, "open_url") as request:
            app.stream_download(row, part, self.storage, self.event, self.progress)
        request.assert_not_called()

    def test_bad_resume_response_keeps_original_partial(self):
        row = self.row()
        part = self.root / "test.part"
        part.write_bytes(b"PMTiles")
        app.atomic_json(part.with_suffix(".json"), {"url": row["url"], "etag": '"v1"'})
        with patch.object(sources, "open_url", return_value=Response(b"bad", 206, {"Content-Range": "bytes 1-3/4"})):
            with self.assertRaises(ValueError):
                app.stream_download(row, part, self.storage, self.event, self.progress)
        self.assertEqual(part.read_bytes(), b"PMTiles")

    def test_truncated_download_retains_partial(self):
        part = self.root / "test.part"
        with patch.object(sources, "open_url", return_value=Response(b"PMTiles", headers={"Content-Length": "15"})):
            with self.assertRaises(ValueError):
                app.stream_download(self.row(), part, self.storage, self.event, self.progress)
        self.assertEqual(part.read_bytes(), b"PMTiles")

    def test_checksum_and_html_response_rejected(self):
        part = self.root / "test.part"
        for data in [b"<html>not a map", b"PMTiles\x03corrupt"]:
            part.write_bytes(data)
            row = self.row(data)
            row["sha256"] = "0" * 64
            with self.assertRaises(ValueError):
                app.verify(row, part, self.event)

    def test_cancel_before_download_does_not_open_url(self):
        self.event.set()
        with patch.object(sources, "open_url") as request, self.assertRaises(app.Cancelled):
            app.stream_download(self.row(), self.root / "test.part", self.storage, self.event, self.progress)
        request.assert_not_called()

    def archive(self, entries):
        """Create a temporary ZIP from (filename or ZipInfo, bytes) fixture pairs."""
        archive = self.root / "test.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            for name, data in entries:
                bundle.writestr(name, data)
        return archive

    def test_extracts_only_pdfs_into_category(self):
        archive = self.archive([("sub/book.PDF", b"%PDF-test"), ("readme.txt", b"skip")])
        target = self.root / "library" / "Accounting"
        app.extract_pdfs(archive, target, self.storage, self.event, self.progress)
        self.assertEqual((target / "sub/book.PDF").read_bytes(), b"%PDF-test")
        self.assertFalse((target / "readme.txt").exists())

    def test_zip_traversal_absolute_windows_and_symlink_rejected(self):
        link = zipfile.ZipInfo("link.pdf")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for name in ["../outside.pdf", "/absolute.pdf", "C:/drive.pdf", "dir\\evil.pdf", link]:
            with self.subTest(name=name):
                archive = self.archive([(name, b"bad"), ("good.pdf", b"%PDF-test")])
                with self.assertRaises(ValueError):
                    app.extract_pdfs(archive, self.root / "category", self.storage, self.event, self.progress)
                self.assertFalse((self.root / "category").exists())

    def test_extraction_space_includes_expanded_pdfs(self):
        archive = self.archive([("book.pdf", b"x" * 500)])
        with patch.object(self.storage, "space", side_effect=ValueError("Not enough space")) as check:
            with self.assertRaises(ValueError):
                app.extract_pdfs(archive, self.root / "category", self.storage, self.event, self.progress)
        check.assert_called_once_with(500)
        self.assertFalse((self.root / "category").exists())

    def test_existing_category_preserved(self):
        archive = self.archive([("book.pdf", b"new")])
        target = self.root / "category"
        target.mkdir()
        (target / "book.pdf").write_bytes(b"original")
        with self.assertRaises(ValueError):
            app.extract_pdfs(archive, target, self.storage, self.event, self.progress)
        self.assertEqual((target / "book.pdf").read_bytes(), b"original")
        self.assertEqual(list(self.root.glob("extract-*")), [])

    def test_crc_failure_does_not_publish_category(self):
        archive = self.archive([("book.pdf", b"content-to-corrupt")])
        archive.write_bytes(archive.read_bytes().replace(b"content-to-corrupt", b"content-is-broken!"))
        with self.assertRaises(zipfile.BadZipFile):
            app.extract_pdfs(archive, self.root / "category", self.storage, self.event, self.progress)
        self.assertFalse((self.root / "category").exists())
        self.assertEqual(list(self.root.glob("extract-*")), [])

    def test_source_failure_does_not_hide_other_sources_or_cache(self):
        application = app.Application(self.storage)
        cached = sources.item("survivor", "https://www.survivorlibrary.com/library/Cached.ZIP")
        application.catalog[cached["id"]] = cached

        def discover(key, publish):
            if key == "survivor":
                raise OSError("offline")
            publish([sources.item(key, "https://example.org/test." + ("zim" if key == "wiki" else "pmtiles"))])
            return ""

        with patch.object(sources, "discover", side_effect=discover):
            application.refresh_all()
        self.assertEqual(application.sources["maps"]["status"], "available")
        self.assertEqual(application.sources["survivor"]["status"], "unavailable")
        self.assertIn(cached["id"], application.catalog)
        loaded = app.Application(self.storage)
        loaded.load_cache()
        self.assertEqual(len(loaded.catalog), 4)

    def test_queue_rejects_unknown_and_duplicate_downloads(self):
        application = app.Application(self.storage)
        application.internet["status"] = "online"
        row = self.row()
        application.catalog[row["id"]] = row
        with self.assertRaises(ValueError):
            application.enqueue(["unknown"])
        application.enqueue([row["id"], row["id"]])
        application.enqueue([row["id"]])
        self.assertEqual(application.queue.qsize(), 1)

    def test_worker_publishes_all_four_content_types(self):
        application = app.Application(self.storage)
        application.internet["status"] = "online"
        pdf_archive = io.BytesIO()
        with zipfile.ZipFile(pdf_archive, "w") as bundle:
            bundle.writestr("manual.pdf", b"%PDF-1.7 test manual")
            bundle.writestr("readme.txt", b"not extracted")
        payloads = {"maps": b"PMTiles\x03test-map", "wiki": b"ZIM\x04test-wiki", "survivor": pdf_archive.getvalue()}
        from test_routing import pbf
        payloads["routing"] = pbf()
        rows = [sources.item(key, "https://example.org/" + filename, len(payloads[key]))
                for key, filename in [("maps", "State.pmtiles"), ("wiki", "wikipedia.zim"), ("survivor", "Manuals.ZIP"), ("routing", "georgia-latest.osm.pbf")]]
        rows[-1]["md5"] = hashlib.md5(payloads["routing"]).hexdigest()
        for row in rows:
            application.catalog[row["id"]] = row
        responses = [Response(payloads[row["source"]], headers={"Content-Length": str(row["size"])}) for row in rows]
        with patch.object(sources, "open_url", side_effect=responses):
            application.enqueue([row["id"] for row in rows])
            # Process exactly this batch without leaving a background worker.
            real_get = application.queue.get
            count = 0

            def get():
                nonlocal count
                if count == len(rows):
                    raise StopIteration
                count += 1
                return real_get()

            with patch.object(application.queue, "get", side_effect=get), self.assertRaises(StopIteration):
                application.worker()
        self.assertTrue(all(job["status"] == "complete" for job in application.jobs.values()))
        self.assertEqual((self.root / "maps/pmtiles/State.pmtiles").read_bytes(), payloads["maps"])
        self.assertEqual((self.root / "wiki/wikipedia.zim").read_bytes(), payloads["wiki"])
        self.assertEqual((self.root / "maps/osm/georgia-latest.osm.pbf").read_bytes(), payloads["routing"])
        self.assertEqual(len(app.routing.Routing(self.storage).status()["downloads"]), 1)
        self.assertTrue((self.root / "library/Manuals/manual.pdf").is_file())
        self.assertFalse((self.root / "library/Manuals/readme.txt").exists())
        self.assertEqual(list((self.root / ".data_download").iterdir()), [])
        with self.assertRaises(ValueError):
            application.enqueue([rows[0]["id"]])

    def test_offline_startup_reports_storage_but_waits_for_discovery(self):
        application = app.Application(self.storage)
        with patch.object(sources, "internet_available", side_effect=[False, False, True, True]), \
                patch.object(application, "load_cache") as cache, \
                patch.object(self.storage, "status", wraps=self.storage.status) as disk, \
                patch.object(application, "refresh") as refresh:
            application.check_internet()
            application.check_internet()
            snapshot = application.snapshot()
            self.assertEqual(snapshot["internet"]["status"], "offline")
            self.assertEqual(snapshot["internet"]["message"], "No Internet, its really hard to go on like this")
            self.assertTrue(snapshot["storage"]["ready"])
            cache.assert_not_called()
            disk.assert_called_once()
            refresh.assert_not_called()
            with self.assertRaisesRegex(ValueError, "No Internet"):
                application.enqueue(["some-file"])
            application.check_internet()
            application.check_internet()
            self.assertTrue(application.initialized)
            self.assertEqual(application.internet["status"], "online")
            self.assertEqual(application.internet["message"], "")
            cache.assert_called_once()
            self.assertEqual(disk.call_count, 2)
            refresh.assert_called_once()

    def test_disconnect_and_reconnect_update_status_and_refresh(self):
        application = app.Application(self.storage)
        with patch.object(sources, "internet_available", side_effect=[True, False, True]), \
                patch.object(application, "refresh") as refresh:
            application.check_internet()
            application.check_internet()
            self.assertEqual(application.internet["message"], app.OFFLINE_MESSAGE)
            application.check_internet()
            self.assertEqual(application.internet["status"], "online")
            self.assertEqual(refresh.call_count, 2)

    def test_monitor_checks_every_thirty_seconds_without_real_waits(self):
        application = app.Application(self.storage)
        with patch.object(application, "check_internet") as check, \
                patch.object(application.stopping, "is_set", side_effect=[False, False, True]), \
                patch.object(application.stopping, "wait") as wait, \
                patch.object(app.time, "monotonic", side_effect=[100, 103, 130, 135]):
            application.monitor_internet()
        self.assertEqual(check.call_count, 2)
        self.assertEqual([call.args[0] for call in wait.call_args_list], [27, 25])

    def test_manual_refresh_cannot_bypass_offline_gate(self):
        application = app.Application(self.storage)
        with patch.object(app.threading, "Thread") as thread:
            application.refresh()
        thread.assert_not_called()
        self.assertFalse(application.refreshing)


class HTTPTests(unittest.TestCase):
    """Check served routes and POST validation through real loopback HTTP."""

    def setUp(self):
        """Start a local server without discovery and register shutdown cleanup."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.application = app.Application(app.Storage(self.temp.name, require_mount=False, reserve=0))
        self.server = app.make_server(self.application, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def test_page_state_and_health_without_source_network(self):
        for path in ["/", "/app.js", "/style.css", "/api/state", "/api/catalog", "/api/health"]:
            with self.subTest(path=path), urlopen(self.base + path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("nosniff", response.headers["X-Content-Type-Options"])

    def test_post_requires_token_and_cannot_accept_arbitrary_url(self):
        request = Request(self.base + "/api/download", data=b'{"ids":["https://example.org/arbitrary"]}',
                          headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 403)
        request.add_header("X-Library-Token", self.application.token)
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 400)

    def test_routing_selection_requires_token_and_valid_verified_file(self):
        request = Request(self.base + "/api/routing", data=b'{"filename":"georgia-latest.osm.pbf"}',
                          headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 403)
        request.add_header("X-Library-Token", self.application.token)
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 400)
        request.data = b'{"filename":null}'
        with urlopen(request) as response:
            self.assertEqual(response.status, 202)

    def test_restart_is_token_protected_post_only(self):
        with patch.object(app, "restart_available", return_value=True), patch.object(app, "request_host_restart") as restart:
            for method, status in [("GET", 404), ("POST", 403)]:
                request = Request(self.base + "/api/restart", method=method,
                                  data=b'{}' if method == "POST" else None)
                with self.assertRaises(HTTPError) as error:
                    urlopen(request)
                self.assertEqual(error.exception.code, status)
            restart.assert_not_called()
            request = Request(self.base + "/api/restart", data=b'{}',
                              headers={"X-Library-Token": self.application.token})
            with urlopen(request) as response:
                self.assertEqual(response.status, 202)
            restart.assert_called_once()

    def test_broken_access_log_pipe_does_not_abort_http_response(self):
        # A stopped container log collector can leave stderr with no reader.
        broken_log = unittest.mock.Mock()
        broken_log.write.side_effect = BrokenPipeError("container log pipe closed")
        with patch("sys.stderr", broken_log):
            for path in ["/api/health", "/", "/api/state"]:
                with self.subTest(path=path), urlopen(self.base + path, timeout=3) as response:
                    self.assertEqual(response.status, 200)


if __name__ == "__main__":
    unittest.main()
