#!/usr/bin/env python3
"""Serve the Library download UI and manage content on its mounted USB drive.

Run ``python3 app.py`` to start the HTTP server, internet monitor, and single
download worker. Configuration comes from LIBRARY_ROOT, PORT, REQUIRE_MOUNT,
and MIN_FREE_BYTES; importing this module starts no services or network calls.
``sources`` supplies catalog rows; this module owns storage checks, job state,
resumable transfers, validation, extraction, and the browser's JSON API.

See docs/DEVELOPMENT.md for lifecycle/storage details and docs/API.md for the
HTTP contract. All implementation dependencies are in Python's standard library.
"""

import copy
import hashlib
import json
import logging
import os
import queue
import re
import secrets
import signal
import shutil
import stat
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath

import sources

CHUNK = 1024 * 1024
STATIC = Path(__file__).parent / "static"
ACTIVE = {"queued", "downloading", "verifying", "extracting"}
INTERNET_POLL_SECONDS = 30
OFFLINE_MESSAGE = "No Internet, its really hard to go on like this"


class Cancelled(Exception):
    """Signal an operator cancellation without treating it as a failed job."""
    pass


def check_cancel(event):
    """Raise Cancelled when the job's threading.Event has been set."""
    if event.is_set():
        raise Cancelled("Cancelled; download can be retried")


class Storage:
    """Validate destinations and measure space on one Library filesystem.

    ``require_mount=False`` is for deliberate development directories. Space
    values are bytes; ``reserve`` remains free in addition to a requested write.
    Checks do not create the root or turn an ordinary host folder into a USB mount.
    """

    def __init__(self, root, require_mount=True, reserve=256 * CHUNK):
        """Record an absolute root and policy; defer filesystem checks to use."""
        self.root = Path(root).absolute()
        self.require_mount = require_mount
        self.reserve = reserve

    def check(self):
        """Raise ValueError if the root is missing, unmounted, or not writable."""
        if not self.root.is_dir():
            raise ValueError(f"{self.root} is missing. Mount the Library USB drive first.")
        if self.require_mount and not os.path.ismount(self.root):
            raise ValueError(f"{self.root} is not a mount point. Bind-mount the Library USB drive.")
        if not os.access(self.root, os.W_OK):
            raise ValueError(f"{self.root} is not writable")

    def path(self, relative):
        """Return a checked Path without creating it.

        Reject absolute paths, parent traversal, existing symlink components,
        and existing destinations on a different filesystem from the root.
        """
        self.check()
        parts = PurePosixPath(relative).parts
        if not parts or PurePosixPath(relative).is_absolute() or ".." in parts:
            raise ValueError("Invalid storage path")
        path = self.root
        for part in parts:
            path = path / part
            if path.is_symlink():
                raise ValueError(f"Refusing symlink in destination: {path}")
            if path.exists() and path.stat().st_dev != self.root.stat().st_dev:
                raise ValueError(f"Destination is on a different filesystem: {path}")
        return path

    def space(self, needed=0):
        """Return disk usage, or raise if needed bytes plus reserve will not fit."""
        self.check()
        usage = shutil.disk_usage(self.root)
        if needed + self.reserve > usage.free:
            raise ValueError("Not enough free space on /Library (including the free-space reserve)")
        return usage

    def status(self):
        """Return UI-ready capacity fields or a ready=False error dictionary."""
        try:
            self.check()
            usage = shutil.disk_usage(self.root)
            return {"ready": True, "total": usage.total, "used": usage.used,
                    "free": usage.free, "available": max(0, usage.free - self.reserve),
                    "reserve": self.reserve, "path": str(self.root)}
        except (ValueError, OSError) as exc:
            return {"ready": False, "error": str(exc), "path": str(self.root)}


def atomic_json(path, value):
    """Replace JSON via a sibling .tmp file; the caller validates its directory."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


def stream_download(row, part, storage, event, progress):
    """Stream a catalog row's URL into a .part file, leaving failures retryable.

    Args:
        row: Catalog dictionary from sources.item(), including URL and size.
        part: Validated temporary Path on the destination filesystem.
        storage: Storage used to recheck available space before each write.
        event: Cancellation threading.Event, checked between network reads.
        progress: Callback accepting job field updates as keyword arguments.

    A sibling .json stores the URL, length, and HTTP validator for Range/If-Range
    retries. Resume requires a matching URL and ETag or Last-Modified; a full
    200 response restarts the file. This function checks transfer lengths but
    leaves format/checksum verification and final publication to the worker.
    Network, filesystem, ValueError, and Cancelled exceptions propagate.
    """
    metadata = part.with_suffix(".json")
    headers = {}
    offset = 0
    previous = {}
    if part.exists() and metadata.exists():
        try:
            previous = json.loads(metadata.read_text())
        except (ValueError, OSError):
            pass
        validator = previous.get("etag") or previous.get("last_modified")
        if previous.get("url") == row["url"] and validator:
            offset = part.stat().st_size
            headers = {"Range": f"bytes={offset}-", "If-Range": validator}
    expected = row.get("size")
    completed_size = expected if expected is not None else previous.get("total")
    if offset and completed_size == offset:
        progress(status="verifying", downloaded=offset, total=completed_size)
        return
    check_cancel(event)
    if expected:
        storage.space(max(0, expected - offset))
    with sources.open_url(row["url"], headers) as response:
        if response.status == 206:
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
            if not match or int(match[1]) != offset or not headers:
                raise ValueError("Invalid server resume response")
            total = int(match[3])
            if int(match[2]) != total - 1:
                raise ValueError("Server returned an incomplete range")
            current_validator = response.headers.get("ETag") or response.headers.get("Last-Modified")
            if current_validator and current_validator != (previous.get("etag") or previous.get("last_modified")):
                raise ValueError("Source changed while resuming; refresh the catalog")
        elif response.status == 200:
            offset = 0
            length = response.headers.get("Content-Length")
            total = int(length) if length else expected
        else:
            raise ValueError(f"Unexpected HTTP status {response.status}")
        if expected is not None and total is not None and expected != total:
            raise ValueError("Source size changed; refresh the catalog before retrying")
        if response.headers.get("Content-Encoding", "identity") != "identity":
            raise ValueError("Source returned an unsupported content encoding")
        storage.space(max(0, (total or 0) - offset))
        downloaded = offset
        # Open/truncate before recording the new validator, so an interrupted
        # replacement cannot associate old bytes with the new source version.
        with part.open("ab" if offset else "wb") as output:
            etag = response.headers.get("ETag")
            atomic_json(metadata, {"url": row["url"],
                                   "total": total,
                                   "etag": etag if etag and not etag.startswith("W/") else None,
                                   "last_modified": response.headers.get("Last-Modified")})
            progress(status="downloading", downloaded=downloaded, total=total)
            while True:
                check_cancel(event)
                block = response.read(CHUNK)
                if not block:
                    break
                storage.space(len(block))
                output.write(block)
                downloaded += len(block)
                if total is not None and downloaded > total:
                    raise ValueError("Source sent more bytes than expected")
                progress(downloaded=downloaded)
            output.flush()
            os.fsync(output.fileno())
        if total is not None and downloaded != total:
            raise ValueError("Download was interrupted before the complete file arrived; retry to resume")


def verify(row, path, event):
    """Check length, format signature, and any catalog SHA-256 before publication.

    ZIP recognition occurs here; PDF CRC checks happen during extraction. ZIM
    validation checks its header/known size, not the archive's internal checksum.
    Raise ValueError for invalid content and Cancelled during map hashing.
    """
    if row.get("size") is not None and path.stat().st_size != row["size"]:
        raise ValueError("Downloaded file size does not match the catalog")
    if row["source"] == "survivor" and not zipfile.is_zipfile(path):
        raise ValueError("Source did not return a valid ZIP file")
    with path.open("rb") as downloaded:
        magic = downloaded.read(8)
        if row["source"] == "maps" and not magic.startswith(b"PMTiles"):
            raise ValueError("Source did not return a PMTiles file")
        if row["source"] == "wiki" and not magic.startswith(b"ZIM\x04"):
            raise ValueError("Source did not return a ZIM file")
        if row.get("sha256"):
            downloaded.seek(0)
            digest = hashlib.sha256()
            while block := downloaded.read(CHUNK):
                check_cancel(event)
                digest.update(block)
            if digest.hexdigest() != row["sha256"]:
                raise ValueError("Map SHA-256 does not match its Git LFS metadata")


def extract_pdfs(archive, target, storage, event, progress):
    """Extract PDF members to a staging directory and rename it to target.

    Validate archive paths and expanded PDF sizes before writing. Read selected
    members to EOF for CRC validation, check cancellation/space between chunks,
    and report extracted/extract_total bytes through the progress callback.
    Refuse an existing category; clean staging on normal exceptions. The caller
    owns deleting the ZIP after success. Abrupt process termination can leave
    staging behind. PDF contents themselves are not parsed or authenticated.
    """
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if len(members) > 100000:
            raise ValueError("ZIP contains too many entries")
        pdfs, seen = [], set()
        for member in members:
            name = member.filename
            path = PurePosixPath(name)
            mode = member.external_attr >> 16
            if (path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name
                    or any(ord(c) < 32 for c in name) or stat.S_ISLNK(mode)):
                raise ValueError("ZIP contains an unsafe path or symlink")
            if not member.is_dir() and path.suffix.lower() == ".pdf":
                if name.casefold() in seen:
                    raise ValueError("ZIP contains duplicate PDF paths")
                seen.add(name.casefold())
                pdfs.append(member)
        if not pdfs:
            raise ValueError("ZIP does not contain PDF files")
        expanded = sum(member.file_size for member in pdfs)
        storage.space(expanded)  # Downloaded ZIP already occupies disk space.
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="extract-", dir=archive.parent))
        try:
            progress(status="extracting", extracted=0, extract_total=expanded)
            extracted = 0
            for member in pdfs:
                check_cancel(event)
                destination = staging / member.filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, destination.open("xb") as output:
                    while block := source.read(CHUNK):
                        check_cancel(event)
                        storage.space(len(block))
                        output.write(block)
                        extracted += len(block)
                        progress(extracted=extracted)
                # ZipExtFile verifies each PDF's CRC when read to EOF.
            check_cancel(event)
            if target.exists():
                raise ValueError("Destination already exists; existing content was kept")
            staging.rename(target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)


class Application:
    """Coordinate the shared catalog, connectivity state, and sequential queue.

    HTTP handlers, discovery, the internet monitor, and the worker share mutable
    state under an RLock. Catalog metadata and partial downloads persist on disk;
    jobs, cancellation events, the request token, and history are process-local.
    """

    def __init__(self, storage):
        """Initialize state without probing the network or reading the drive."""
        self.storage = storage
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(32)
        self.catalog = {}
        self.sources = {key: {**value, "status": "waiting", "count": 0, "error": ""}
                        for key, value in sources.SOURCES.items()}
        self.jobs = {}
        self.events = {}
        self.queue = queue.Queue()
        self.refreshing = False
        self.internet = {"status": "checking", "message": "Checking internet connection…"}
        self.initialized = False
        self.stopping = threading.Event()

    def load_cache(self):
        """Load persisted catalog rows; missing/unreadable caches are nonfatal.

        The startup monitor calls this under the application lock after its
        first successful internet check. This does not restore queued jobs.
        """
        try:
            cache = json.loads(self.storage.path(".data_download/catalog.json").read_text())
            for row in cache:
                if row["source"] in self.sources:
                    self.catalog[row["id"]] = row
            for key, source in self.sources.items():
                source.update(status="cached", count=sum(r["source"] == key for r in cache))
        except (OSError, ValueError, KeyError, TypeError):
            self.catalog = {}

    def start(self):
        """Start daemon worker/monitor threads once; discovery waits for internet."""
        threading.Thread(target=self.worker, daemon=True, name="download-worker").start()
        threading.Thread(target=self.monitor_internet, daemon=True, name="internet-monitor").start()

    def check_internet(self):
        """Probe connectivity, initialize storage/cache once, refresh on recovery."""
        online = sources.internet_available()
        with self.lock:
            previous = self.internet["status"]
            self.internet.update(status="online" if online else "offline",
                                 message="" if online else OFFLINE_MESSAGE)
            if online and not self.initialized:
                logging.info("Storage after internet check: %s", self.storage.status())
                self.load_cache()
                self.initialized = True
        if online and previous != "online":
            self.refresh()

    def monitor_internet(self):
        """Probe immediately, then on a 30-second cadence until stopping is set."""
        while not self.stopping.is_set():
            started = time.monotonic()
            self.check_internet()
            # Keep a 30-second polling cadence, including time spent probing.
            self.stopping.wait(max(0, INTERNET_POLL_SECONDS - (time.monotonic() - started)))

    def refresh(self):
        """Start one asynchronous catalog refresh if online and no scan is active."""
        with self.lock:
            if self.refreshing or self.internet["status"] != "online":
                return
            self.refreshing = True
            for source in self.sources.values():
                source.update(status="checking", error="")
        threading.Thread(target=self.refresh_all, daemon=True, name="catalog-discovery").start()

    def refresh_all(self):
        """Scan sources independently, merge progressive results, and save cache.

        Successful scans replace that source's stale rows. Failed/partial scans
        keep earlier rows available. Source and cache errors are reported without
        stopping the other scans; refreshing is cleared after cache handling.
        """
        def scan(key):
            """Discover one source and record availability or its failure reason."""
            fresh = {}

            def publish(rows):
                """Merge a discovered batch under the lock for live UI updates."""
                with self.lock:
                    for row in rows:
                        fresh[row["id"]] = row
                        self.catalog[row["id"]] = row
                    self.sources[key]["count"] = len(fresh)

            try:
                warning = sources.discover(key, publish)
                with self.lock:
                    if not warning:
                        self.catalog = {k: v for k, v in self.catalog.items()
                                        if v["source"] != key or k in fresh}
                    if not fresh:
                        raise ValueError(warning or "No downloadable files found")
                    self.sources[key].update(status="partial" if warning else "available",
                                             error=warning, checked_at=time.time())
            except Exception as exc:
                logging.warning("%s discovery: %s", key, exc)
                with self.lock:
                    self.sources[key].update(status="unavailable", error=str(exc))

        threads = [threading.Thread(target=scan, args=(key,)) for key in self.sources]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        try:
            cache = self.storage.path(".data_download/catalog.json")
            cache.parent.mkdir(exist_ok=True)
            with self.lock:
                atomic_json(cache, list(self.catalog.values()))
        except (OSError, ValueError) as exc:
            logging.warning("Catalog cache: %s", exc)
        finally:
            with self.lock:
                self.refreshing = False

    def enqueue(self, ids):
        """Queue 1–100 catalog IDs, validating the batch before adding jobs.

        Refuse requests while offline, unknown IDs, or existing destinations.
        Ignore duplicate IDs and already-active jobs; retry terminal jobs with
        fresh in-memory state while retaining any resumable files on disk.
        """
        if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or not all(isinstance(i, str) for i in ids):
            raise ValueError("Select between 1 and 100 catalog files")
        with self.lock:
            if self.internet["status"] != "online":
                raise ValueError(self.internet["message"])
        self.storage.space()
        with self.lock:
            rows = []
            for identity in dict.fromkeys(ids):
                if identity not in self.catalog:
                    raise ValueError("Unknown catalog file; refresh the page")
                if identity in self.jobs and self.jobs[identity]["status"] in ACTIVE:
                    continue
                row = copy.deepcopy(self.catalog[identity])
                if self.storage.path(row["destination"]).exists():
                    raise ValueError(f"Destination already exists: {row['destination']}")
                rows.append(row)
            for row in rows:
                identity = row["id"]
                self.events[identity] = threading.Event()
                self.jobs[identity] = {"id": identity, "title": row["title"],
                                       "status": "queued", "downloaded": 0,
                                       "total": row["size"], "error": "",
                                       "destination": row["destination"]}
                self.queue.put(row)

    def cancel(self, identity):
        """Set a known job's event; cancellation takes effect at its next check."""
        with self.lock:
            if identity not in self.events:
                raise ValueError("Unknown download")
            self.events[identity].set()

    def update(self, identity, **changes):
        """Apply worker progress fields while holding the shared-state lock."""
        with self.lock:
            self.jobs[identity].update(changes)

    def worker(self):
        """Consume jobs serially through transfer, verification, and publication.

        Keep retryable partials, remove format/checksum-invalid transfers, and
        remove corrupt ZIPs on BadZipFile. Record a terminal status for each
        attempt. The daemon blocks on an empty queue; it is not a job scheduler
        that automatically retries failures or restores work after a restart.
        """
        while True:
            row = self.queue.get()
            identity = row["id"]
            event = self.events[identity]
            progress = lambda **changes: self.update(identity, **changes)
            try:
                check_cancel(event)
                target = self.storage.path(row["destination"])
                if target.exists():
                    raise ValueError("Destination already exists; existing content was kept")
                part = self.storage.path(f".data_download/{identity}.part")
                part.parent.mkdir(exist_ok=True)
                progress(status="downloading")
                stream_download(row, part, self.storage, event, progress)
                progress(status="verifying")
                check_cancel(event)
                try:
                    verify(row, part, event)
                except ValueError:
                    part.unlink(missing_ok=True)
                    part.with_suffix(".json").unlink(missing_ok=True)
                    raise
                # Recheck paths and mount immediately before publishing.
                target = self.storage.path(row["destination"])
                if row["source"] == "survivor":
                    try:
                        extract_pdfs(part, target, self.storage, event, progress)
                    except zipfile.BadZipFile:
                        part.unlink(missing_ok=True)
                        part.with_suffix(".json").unlink(missing_ok=True)
                        raise
                    part.unlink()
                else:
                    check_cancel(event)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        raise ValueError("Destination already exists; existing content was kept")
                    part.rename(target)
                part.with_suffix(".json").unlink(missing_ok=True)
                progress(status="complete")
            except Cancelled as exc:
                progress(status="cancelled", error=str(exc))
            except Exception as exc:
                logging.exception("Download failed: %s", row["filename"])
                progress(status="failed", error=str(exc))
            finally:
                self.queue.task_done()

    def snapshot(self, include_catalog=False):
        """Copy browser state, optionally adding sorted rows and installed flags.

        Report storage as waiting before the first successful internet check.
        Installed flags indicate destination existence, not an integrity audit.
        """
        with self.lock:
            disk = self.storage.status() if self.initialized else {
                "ready": False, "path": str(self.storage.root), "error": "Waiting for internet connection"}
            result = {"storage": disk, "internet": self.internet.copy(),
                      "sources": copy.deepcopy(self.sources),
                      "refreshing": self.refreshing, "jobs": copy.deepcopy(list(self.jobs.values())),
                      "token": self.token}
            if include_catalog:
                rows = copy.deepcopy(list(self.catalog.values()))
                for row in rows:
                    try:
                        row["installed"] = self.storage.path(row["destination"]).exists()
                    except (ValueError, OSError):
                        row["installed"] = False
                result["catalog"] = sorted(rows, key=lambda r: (r["source"], r["title"].lower()))
            return result


class Handler(BaseHTTPRequestHandler):
    """Serve fixed local assets and the JSON API attached as server.app.

    POST requests require the per-process X-Library-Token from a state response.
    This protects browser mutations against cross-origin requests; it is not
    user authentication. See docs/API.md for paths, bodies, and status codes.
    """

    def log_message(self, format, *args):
        """Keep serving if the container's stderr/log collector disconnects.

        BaseHTTPRequestHandler logs before sending response headers. A broken
        log pipe must not turn a healthy request into an empty HTTP response.
        """
        try:
            super().log_message(format, *args)
        except OSError:
            pass

    def respond(self, status, data, content_type="application/json"):
        """Send JSON or asset bytes with a length and restrictive browser headers."""
        body = json.dumps(data).encode() if content_type == "application/json" else data
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        """Serve health/state/catalog or one of the three bundled UI assets."""
        if self.path == "/api/health":
            return self.respond(200, {"status": "ok"})
        if self.path in {"/api/state", "/api/catalog"}:
            return self.respond(200, self.server.app.snapshot(self.path == "/api/catalog"))
        assets = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8")}
        if self.path in assets:
            filename, content_type = assets[self.path]
            return self.respond(200, (STATIC / filename).read_bytes(), content_type)
        self.respond(404, {"error": "Not found"})

    def do_POST(self):
        """Validate token and bounded JSON body, then dispatch a queue action."""
        if not secrets.compare_digest(self.headers.get("X-Library-Token", ""), self.server.app.token):
            return self.respond(403, {"error": "Reload the page before making changes"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise ValueError("Invalid request size")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object")
            if self.path == "/api/download":
                self.server.app.enqueue(body.get("ids"))
            elif self.path == "/api/refresh":
                self.server.app.refresh()
            elif self.path == "/api/cancel":
                identity = body.get("id")
                if not isinstance(identity, str):
                    raise ValueError("Invalid download ID")
                self.server.app.cancel(identity)
            else:
                return self.respond(404, {"error": "Not found"})
            self.respond(202, {"ok": True})
        except (ValueError, OSError) as exc:
            self.respond(400, {"error": str(exc)})


def make_server(app, host="0.0.0.0", port=4286):
    """Bind a threaded HTTP server and attach app; the caller starts serving."""
    server = ThreadingHTTPServer((host, port), Handler)
    server.app = app
    return server


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    storage = Storage(os.environ.get("LIBRARY_ROOT", "/Library"),
                      require_mount=os.environ.get("REQUIRE_MOUNT", "1") != "0",
                      reserve=max(0, int(os.environ.get("MIN_FREE_BYTES", str(256 * CHUNK)))))
    app = Application(storage)
    server = make_server(app, port=int(os.environ.get("PORT", "4286")))
    app.start()
    logging.info("Library Data Download listening on %s:%s", *server.server_address)
    # Python is PID 1 in the container; explicitly handle Podman's stop signal.
    def stop(signum, frame):
        """Route SIGTERM through the same shutdown path as Ctrl-C."""
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        app.stopping.set()
        with app.lock:
            for event in app.events.values():
                event.set()
        server.server_close()
