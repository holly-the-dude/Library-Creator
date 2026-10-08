"""Routing discovery, download integrity and safe boot activation regressions.

Use tiny synthetic OSM-header fixtures and temporary storage; no remote files,
containers, active routing service, or real /Library mount are touched.
"""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import routing
import sources


def pbf(data=b"routing fixture"):
    header = b"\x0a\x09OSMHeader\x18" + bytes([len(data)])
    return len(header).to_bytes(4, "big") + header + data


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = app.Storage(self.root, require_mount=False, reserve=0)
        self.manager = routing.Routing(self.storage)
        self.content = pbf()
        self.row = sources.item("routing", "https://download.geofabrik.de/north-america/us/georgia-latest.osm.pbf",
                                len(self.content), title="Georgia · routing")
        self.row["md5"] = hashlib.md5(self.content).hexdigest()

    def downloaded(self):
        path = self.storage.path(self.row["destination"])
        path.parent.mkdir(parents=True)
        path.write_bytes(self.content)
        app.verify(self.row, path, threading.Event())
        self.manager.record_download(self.row)
        return path

    def old_region(self):
        active = self.manager.path("region.osm.pbf")
        active.write_bytes(b"previous region")
        marker = self.storage.path("maps/graph-cache/properties")
        marker.parent.mkdir(parents=True)
        marker.write_text("previous completed graph")
        return active, marker

    def test_catalog_only_current_us_https_regional_extracts(self):
        html = '''<a href="us/georgia-latest.osm.pbf">Georgia</a>
          <a href="us/new-york-latest.osm.pbf">NY</a>
          <a href="us/georgia-latest.osm.pbf">duplicate</a>
          <a href="us/georgia-260101.osm.pbf">old</a>
          <a href="us-latest.osm.pbf">whole US</a>
          <a href="https://example.org/north-america/us/georgia-latest.osm.pbf">evil</a>
          <a href="http://download.geofabrik.de/north-america/us/georgia-latest.osm.pbf">http</a>
          <a href="us/georgia-latest.osm.pbf?url=evil">query</a>'''
        self.assertEqual(sources.routing_links(html), [self.row["url"], self.row["url"].replace("georgia", "new-york")])

    def test_exact_head_size_and_checksum(self):
        response = io.BytesIO()
        response.headers = {"Content-Length": "123456"}
        with patch.object(sources, "urlopen", return_value=response) as request, \
             patch.object(sources, "fetch", return_value="a" * 32 + "  georgia-latest.osm.pbf\n"):
            row = sources.routing_item(self.row["url"])
        self.assertEqual(request.call_args.args[0].get_method(), "HEAD")
        self.assertEqual(row["size"], 123456)
        self.assertEqual(row["md5"], "a" * 32)
        self.assertEqual(row["destination"], "maps/osm/georgia-latest.osm.pbf")

    def test_verify_rejects_bad_header_and_checksum(self):
        path = self.root / "download.part"
        for content in (b"<html>not a PBF</html>", pbf(b"damaged fixture")):
            path.write_bytes(content)
            row = {**self.row, "size": len(content)}
            with self.assertRaises(ValueError):
                app.verify(row, path, threading.Event())

    def test_cancel_during_hashing(self):
        path = self.root / "download.part"
        path.write_bytes(self.content)
        event = threading.Event()
        event.set()
        with self.assertRaises(app.Cancelled):
            app.verify(self.row, path, event)

    def test_select_only_queues_and_survives_process_restart(self):
        self.downloaded()
        active, marker = self.old_region()
        self.manager.select(self.row["filename"])
        state = routing.Routing(self.storage).status()
        self.assertEqual(state["pending"]["filename"], self.row["filename"])
        self.assertEqual(len(state["downloads"]), 1)
        self.assertEqual(active.read_bytes(), b"previous region")
        self.assertTrue(marker.exists())

    def test_activate_copies_verified_data_and_invalidates_graph(self):
        source = self.downloaded()
        active, marker = self.old_region()
        self.manager.select(self.row["filename"])
        self.assertTrue(self.manager.activate())
        self.assertEqual(active.read_bytes(), self.content)
        self.assertEqual(source.read_bytes(), self.content)
        self.assertFalse(marker.exists())
        self.assertIsNone(self.manager.status()["pending"])
        self.assertEqual(self.manager.status()["active"]["filename"], self.row["filename"])
        self.assertFalse(self.manager.activate())

    def test_changed_download_keeps_previous_region_cache_and_request(self):
        source = self.downloaded()
        active, marker = self.old_region()
        self.manager.select(self.row["filename"])
        source.write_bytes(self.content[:-1] + b"!")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.manager.activate()
        self.assertEqual(active.read_bytes(), b"previous region")
        self.assertTrue(marker.exists())
        self.assertIsNotNone(self.manager.status()["pending"])
        self.assertEqual(list(source.parent.glob(".routing-*")), [])

    def test_insufficient_activation_space_preserves_previous_data(self):
        self.downloaded()
        active, marker = self.old_region()
        self.manager.select(self.row["filename"])
        with patch.object(self.storage, "space", side_effect=ValueError("Not enough free space")):
            with self.assertRaises(ValueError):
                self.manager.activate()
        self.assertEqual(active.read_bytes(), b"previous region")
        self.assertTrue(marker.exists())

    def test_cancel_selection_preserves_active_and_download(self):
        source = self.downloaded()
        active, marker = self.old_region()
        self.manager.select(self.row["filename"])
        self.manager.select(None)
        self.assertIsNone(self.manager.status()["pending"])
        self.assertTrue(source.exists() and marker.exists())
        self.assertEqual(active.read_bytes(), b"previous region")

    def test_unverified_and_unsafe_selections_rejected(self):
        self.downloaded()
        for filename in ["../region.osm.pbf", "missing-latest.osm.pbf", {}, "region.osm.pbf"]:
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                self.manager.select(filename)

    def test_symlink_active_destination_cannot_modify_external_file(self):
        self.downloaded()
        outside = self.root / "keep"
        outside.write_bytes(b"keep")
        self.manager.path("region.osm.pbf").symlink_to(outside)
        self.manager.select(self.row["filename"])
        with self.assertRaises(ValueError):
            self.manager.activate()
        self.assertEqual(outside.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
