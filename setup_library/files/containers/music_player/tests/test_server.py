import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from server import create_server


class LibraryServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "music"
        album = self.root / "Artist & Friends" / "Album café"
        album.mkdir(parents=True)
        self.audio = bytes(range(256)) * 8
        self.track = album / "02 - Song #é.MP3"
        self.track.write_bytes(self.audio)
        (album / "10 - Finale.wav").write_bytes(b"audio")
        (self.root / "Root.m4a").write_bytes(b"root audio")
        (self.root / "ignored.m3u").write_text("playlist")
        (self.root / ".hidden.mp3").write_bytes(b"hidden")
        hidden = self.root / ".hidden"
        hidden.mkdir()
        (hidden / "song.mp3").write_bytes(b"hidden")
        self.outside = Path(self.temp.name) / "private.mp3"
        self.outside.write_bytes(b"private")
        (self.root / "outside.mp3").symlink_to(self.outside)
        (self.root / "loop").symlink_to(self.root, target_is_directory=True)
        self.server = create_server(self.root, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, headers=None, method="GET"):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def library(self):
        status, _, body = self.request("/api/library")
        self.assertEqual(status, 200)
        return json.loads(body)

    def track_url(self):
        return "/" + next(song["previewUrl"] for song in self.library()["songs"]
                          if song["name"].startswith("02"))

    def test_recursive_library_and_folder_relationships(self):
        data = self.library()
        self.assertEqual(len(data["songs"]), 3)
        self.assertEqual(data["playlists"], [])
        root, artist, album = data["folders"]
        self.assertIsNone(root["parentId"])
        self.assertEqual(artist["parentId"], "root")
        self.assertEqual(album["parentId"], artist["id"])
        song_by_id = {song["id"]: song for song in data["songs"]}
        self.assertEqual([song_by_id[sid]["name"] for sid in album["songIds"]],
                         ["02 - Song #é", "10 - Finale"])
        self.assertEqual(song_by_id[album["songIds"][0]]["artistName"], "Artist & Friends")
        self.assertEqual(song_by_id[album["songIds"][0]]["albumName"], "Album café")
        self.assertTrue(all(song["previewUrl"].startswith("media/") for song in data["songs"]))
        self.assertEqual(self.request(self.track_url())[2], self.audio)

    def test_range_requests_and_head(self):
        url = self.track_url()
        for header, start, end in [("bytes=12-32", 12, 32), ("bytes=2000-", 2000, 2047),
                                    ("bytes=-20", 2028, 2047), ("bytes=2040-9000", 2040, 2047)]:
            with self.subTest(header=header):
                status, headers, body = self.request(url, {"Range": header})
                self.assertEqual(status, 206)
                self.assertEqual(headers["Content-Range"], f"bytes {start}-{end}/2048")
                self.assertEqual(headers["Content-Type"], "audio/mpeg")
                self.assertEqual(body, self.audio[start:end + 1])
        status, headers, body = self.request(url, {"Range": "bytes=0-1"}, method="HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Length"], "2048")
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertEqual(body, b"")
        for invalid in ["bytes=5000-", "bytes=10-1", "bytes=-0", "bytes=", "bytes=0-1,4-5"]:
            with self.subTest(invalid=invalid):
                status, headers, _ = self.request(url, {"Range": invalid})
                self.assertEqual(status, 416)
                self.assertEqual(headers["Content-Range"], "bytes */2048")

    def test_rescan_adds_and_removes_tracks(self):
        original_ids = {song["id"] for song in self.library()["songs"]}
        self.assertEqual(original_ids, {song["id"] for song in self.library()["songs"]})
        old_url = self.track_url()
        self.track.unlink()
        (self.root / "new.ogg").write_bytes(b"new")
        names = [song["name"] for song in self.library()["songs"]]
        self.assertIn("new", names)
        self.assertNotIn("02 - Song #é", names)
        self.assertEqual(self.request(old_url)[0], 404)

    def test_cannot_serve_files_outside_root_or_app(self):
        for path in ["/../private.mp3", "/media/../private.mp3", "/media/%2e%2e/private.mp3", "/server.py"]:
            self.assertEqual(self.request(path)[0], 404)
        url = self.track_url()
        self.track.unlink()
        self.track.symlink_to(self.outside)
        self.assertEqual(self.request(url)[0], 404)

    def test_empty_library_and_unavailable_library(self):
        with tempfile.TemporaryDirectory() as empty:
            self.server.library.root = Path(empty)
            data = self.library()
            self.assertEqual(data["songs"], [])
            self.assertEqual(len(data["folders"]), 1)
        self.assertEqual(self.request("/api/library")[0], 503)
        with patch.object(self.server.library, "scan", side_effect=PermissionError("unreadable")):
            self.assertEqual(self.request("/api/library")[0], 503)

    def test_local_music_ui_served(self):
        status, _, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"library-music-player", body)
        self.assertEqual(self.request("/music.html")[2], body)
        self.assertNotIn(b"window.fetch =", body)


if __name__ == "__main__":
    unittest.main()
