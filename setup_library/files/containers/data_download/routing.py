#!/usr/bin/env python3
"""Persist routing choices and activate a verified extract at Library startup.

The web app records a choice only. The startup playbook stops GraphHopper and
runs this module inside the downloader image with /Library mounted. No Podman
socket, network access, or service control is exposed to the web application.
"""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

CHUNK = 1024 * 1024
FILENAME = re.compile(r"[a-z][a-z-]*-latest\.osm\.pbf")


def check_pbf(path):
    """Recognize the initial OSMHeader blob; this is not a full protobuf parser."""
    with path.open("rb") as stream:
        size = int.from_bytes(stream.read(4), "big")
        if not 0 < size <= 65536:
            raise ValueError("Invalid OSM PBF header length")
        header = stream.read(size)
        if len(header) != size or b"\x0a\x09OSMHeader" not in header:
            raise ValueError("Source did not return an OSM PBF file")


class Routing:
    """Own downloaded-file receipts and the pending/active routing selections."""

    def __init__(self, storage):
        # Storage supplies mount, free-space, and symlink/path validation.
        self.storage = storage

    def path(self, name):
        return self.storage.path("maps/osm/" + name)

    @contextmanager
    def locked(self):
        """Serialize selection changes and boot activation across processes."""
        path = self.path(".routing.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def read(self, name):
        """Read a validated receipt; return None for absent or invalid records."""
        try:
            record = json.loads(self.path(name).read_text())
            if (not isinstance(record, dict)
                    or not isinstance(record.get("filename"), str)
                    or not FILENAME.fullmatch(record["filename"])
                    or not isinstance(record.get("sha256"), str)
                    or not re.fullmatch(r"[a-f0-9]{64}", record["sha256"])
                    or not isinstance(record.get("size"), int) or record["size"] <= 0):
                return None
            return record
        except (OSError, ValueError):
            return None

    def write(self, name, record):
        """Publish a small receipt atomically on the same filesystem."""
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(record, stream)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(target)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def record_download(self, row):
        """Save verification evidence after a routing download has been published."""
        record = {key: row[key] for key in ("filename", "title", "size", "sha256")}
        self.write(row["filename"] + ".json", record)

    def status(self):
        """List verified downloads and choices without hashing large PBF files."""
        try:
            directory = self.path("routing-pending.json").parent
            downloads = []
            for path in sorted(directory.glob("*-latest.osm.pbf.json")):
                record = self.read(path.name)
                if record:
                    source = self.path(record["filename"])
                    if source.is_file() and source.stat().st_size == record["size"]:
                        downloads.append(record)
            error = self.path("routing-error.txt")
            return {"downloads": downloads, "pending": self.read("routing-pending.json"),
                    "active": self.read("routing-active.json"),
                    "error": error.read_text()[:4096] if error.exists() else ""}
        except (OSError, ValueError) as exc:
            return {"downloads": [], "pending": None, "active": None, "error": str(exc)}

    def select(self, filename):
        """Queue one verified region for next boot, or cancel with None.

        This never changes the active extract or graph while the Pi is serving.
        Reserving enough space for a second copy preserves the old active file
        until the new copy has passed its startup checksum check.
        """
        with self.locked():
            if filename is None:
                self.path("routing-pending.json").unlink(missing_ok=True)
                self.path("routing-error.txt").unlink(missing_ok=True)
                return
            if not isinstance(filename, str) or not FILENAME.fullmatch(filename):
                raise ValueError("Choose a downloaded routing region")
            record = self.read(filename + ".json")
            source = self.path(filename)
            if not record or record["filename"] != filename or not source.is_file() or source.stat().st_size != record["size"]:
                raise ValueError("Routing file is missing or unverified; download it again")
            self.storage.space(record["size"])
            self.write("routing-pending.json", record)
            self.path("routing-error.txt").unlink(missing_ok=True)

    def activate(self):
        """Copy/check selected data, invalidate the graph, then publish atomically.

        Caller MUST stop GraphHopper first. Failed copies/checks keep the old
        active extract and the pending request. A cleared properties marker makes
        start_library.yml rebuild the derived graph on this or the next boot.
        """
        with self.locked():
            request = self.path("routing-pending.json")
            if not request.exists():
                return False
            record = self.read(request.name)
            if not record:
                raise ValueError("Invalid pending routing request")
            source = self.path(record["filename"])
            if source.stat().st_size != record["size"]:
                raise ValueError("Selected routing file size changed")
            check_pbf(source)
            self.storage.space(record["size"])
            target = self.path("region.osm.pbf")
            temporary = None
            try:
                digest = hashlib.sha256()
                with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".routing-", delete=False) as output:
                    temporary = Path(output.name)
                    with source.open("rb") as incoming:
                        while block := incoming.read(CHUNK):
                            self.storage.space(len(block))
                            digest.update(block)
                            output.write(block)
                    output.flush()
                    os.fsync(output.fileno())
                if digest.hexdigest() != record["sha256"]:
                    raise ValueError("Selected routing file checksum changed; previous region kept")
                temporary.chmod(0o644)
                # Invalidate only the completion marker. The boot playbook owns
                # removal of derived graph files after the routing service stops.
                self.storage.path("maps/graph-cache/properties").unlink(missing_ok=True)
                temporary.replace(target)
                self.write("routing-active.json", record)
                self.path("routing-error.txt").unlink(missing_ok=True)
                request.unlink()
                return True
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    # Imported only for CLI use to share the downloader's existing storage policy.
    from app import Storage
    storage = Storage(os.environ.get("LIBRARY_ROOT", "/Library"),
                      reserve=max(0, int(os.environ.get("MIN_FREE_BYTES", str(256 * CHUNK)))))
    manager = Routing(storage)
    try:
        changed = manager.activate()
    except (OSError, ValueError) as exc:
        try:
            manager.path("routing-error.txt").write_text(str(exc))
        except (OSError, ValueError):
            pass
        raise
    print("Routing selection activated" if changed else "No pending routing selection")
