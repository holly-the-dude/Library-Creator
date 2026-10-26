#!/usr/bin/env python3
"""Serve the music player UI and a read-only music library. Requires Python 3.10+."""

import argparse
import hashlib
import json
import logging
import os
import re
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


APP_DIR = Path(__file__).resolve().parent
AUDIO_TYPES = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}


def identifier(kind, value):
    return kind + hashlib.sha256(value.encode("utf-8")).hexdigest()


def natural_key(value):
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r"(\d+)", value)]


class Library:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Music path must be a directory")
        self.files = {}
        self.lock = threading.Lock()

    def scan(self):
        # Serialize scans, then replace the index atomically for concurrent streams.
        with self.lock:
            songs, folders, artists, files = [], [], {}, {}

            def fail(error):
                raise error

            for directory, names, filenames in os.walk(self.root, onerror=fail, followlinks=False):
                parent = Path(directory)
                names[:] = sorted((name for name in names
                                   if not name.startswith(".") and not (parent / name).is_symlink()),
                                  key=natural_key)
                relative = parent.relative_to(self.root)
                folder_id = "root" if parent == self.root else identifier("folder-", relative.as_posix())
                parent_id = (None if parent == self.root else "root" if parent.parent == self.root
                             else identifier("folder-", relative.parent.as_posix()))
                folder = {"id": folder_id, "parentId": parent_id,
                          "name": "Folders" if parent == self.root else parent.name, "songIds": []}
                folders.append(folder)
                for filename in sorted(filenames, key=natural_key):
                    path = parent / filename
                    if filename.startswith(".") or path.suffix.lower() not in AUDIO_TYPES:
                        continue
                    try:
                        resolved = path.resolve(strict=True)
                        if not resolved.is_relative_to(self.root) or not resolved.is_file():
                            continue
                    except (OSError, RuntimeError):
                        continue
                    track_path = path.relative_to(self.root).as_posix()
                    song_id = identifier("song-", track_path)
                    # No tag reader is needed: Artist/Album/song.ext works offline.
                    artist_name = relative.parts[0] if relative.parts else "Unknown Artist"
                    artist_id = identifier("artist-", artist_name)
                    artist = artists.setdefault(artist_id, {"id": artist_id, "name": artist_name, "songIds": []})
                    songs.append({"id": song_id, "name": path.stem, "artistName": artist_name,
                                  "artistIds": [artist_id], "albumName": parent.name if relative.parts else "",
                                  "previewUrl": "media/" + song_id})
                    folder["songIds"].append(song_id)
                    artist["songIds"].append(song_id)
                    files[song_id] = path
            self.files = files
            return {"schemaVersion": 3, "storefront": "local", "language": "en-US",
                    "songs": songs, "folders": folders,
                    "artists": sorted(artists.values(), key=lambda artist: natural_key(artist["name"])),
                    "playlists": []}

    def media_path(self, song_id):
        path = self.files.get(song_id)
        if path is None:
            raise FileNotFoundError(song_id)
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(self.root) or not resolved.is_file():
            raise FileNotFoundError(song_id)
        return resolved, AUDIO_TYPES[path.suffix.lower()]


def byte_range(header, size):
    """Return an inclusive single byte range, or raise ValueError for HTTP 416."""
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if not match or not any(match.groups()) or size == 0:
        raise ValueError("Invalid byte range")
    start, end = match.groups()
    if not start:
        count = int(end)
        if count <= 0:
            raise ValueError("Invalid suffix range")
        return max(0, size - count), size - 1
    start = int(start)
    end = min(int(end), size - 1) if end else size - 1
    if start >= size or end < start:
        raise ValueError("Unsatisfiable byte range")
    return start, end


class Handler(BaseHTTPRequestHandler):
    server_version = "LocalMusic/1.0"

    def do_GET(self):
        self.handle_request()

    def do_HEAD(self):
        self.handle_request(head=True)

    def handle_request(self, head=False):
        path = urlsplit(self.path).path
        try:
            if path in ("/", "/music.html"):
                self.send_file(APP_DIR / "music.html", "text/html; charset=utf-8", head)
            elif path == "/api/library":
                try:
                    data = self.server.library.scan()
                except OSError:
                    logging.exception("Cannot scan the music directory")
                    self.send_error(503, "Music directory is unavailable or unreadable")
                    return
                body = json.dumps(data, ensure_ascii=True).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if not head:
                    self.wfile.write(body)
            elif path.startswith("/media/"):
                media, content_type = self.server.library.media_path(path[len("/media/"):])
                self.send_file(media, content_type, head, ranges=True)
            else:
                self.send_error(404)
        except (FileNotFoundError, PermissionError, IsADirectoryError, RuntimeError):
            self.send_error(404, "File unavailable")
        except (BrokenPipeError, ConnectionResetError):
            pass  # Browsers cancel media requests when skipping or seeking.

    def send_file(self, path, content_type, head, ranges=False):
        with path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise FileNotFoundError(path)
            size = info.st_size
            start, end = 0, size - 1
            # Range applies only to GET; HEAD returns headers for the full file.
            requested = self.headers.get("Range") if ranges and not head else None
            if requested:
                try:
                    start, end = byte_range(requested, size)
                except ValueError:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            self.send_response(206 if requested else 200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-cache")
            if ranges:
                self.send_header("Accept-Ranges", "bytes")
            if requested:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if head:
                return
            stream.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = stream.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def create_server(root, host="127.0.0.1", port=8080):
    library = Library(root)
    library.scan()  # Fail early on an unreadable mount; media URLs work immediately.
    server = ThreadingHTTPServer((host, port), Handler)
    server.library = library
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--music-dir", default=os.environ.get("MUSIC_DIR", "/music"))
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = parser.parse_args()
    try:
        server = create_server(args.music_dir, args.host, args.port)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Serving {server.library.root} at http://{args.host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
