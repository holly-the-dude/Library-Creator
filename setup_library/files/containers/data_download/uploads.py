"""Stream browser uploads to fixed Library destinations, with safe ZIP extraction."""

import os
from pathlib import PurePosixPath, Path
import shutil
import stat
import tempfile
import zipfile
import zlib

CHUNK = 1024 * 1024
DESTINATIONS = {"music": "music", "data": "library", "ebooks": "calibre/put_new_books_here"}


def safe_path(name):
    """Accept relative browser/ZIP paths without ambiguous or special components."""
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or any(part in {"", ".", ".."} for part in name.split("/"))):
        raise ValueError("Invalid upload path")
    path = PurePosixPath(name)
    if path.is_absolute():
        raise ValueError("Invalid upload path")
    return path


def copy_stream(source, output, storage):
    """Copy in bounded chunks, checking drive capacity before every write."""
    while block := source.read(CHUNK):
        storage.space(len(block))
        output.write(block)


def unpack(archive, staging, storage):
    """Validate all members and CRCs before publishing any archive content."""
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if not members or len(members) > 100000:
            raise ValueError("ZIP must contain between 1 and 100000 entries")
        seen = set()
        entries = []
        for member in members:
            path = safe_path(member.filename[:-1] if member.is_dir() else member.filename)
            mode = stat.S_IFMT(member.external_attr >> 16)
            if mode not in {0, stat.S_IFREG, stat.S_IFDIR} or member.flag_bits & 1:
                raise ValueError("ZIP contains a special file, symlink, or encrypted entry")
            key = str(path).casefold()
            if key in seen:
                raise ValueError("ZIP contains duplicate paths")
            seen.add(key)
            entries.append((member, path))
        storage.space(sum(member.file_size for member, _ in entries))
        for member, path in entries:
            target = staging / path
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, target.open("xb") as output:
                    copy_stream(source, output, storage)


def publish(staging, relative, storage):
    """Merge staged files without overwriting; roll back this upload on failure."""
    paths = sorted(staging.rglob("*"), key=lambda path: (len(path.parts), str(path)))
    # Check the whole batch for collisions before writing any final files.
    for path in paths:
        destination = storage.path(str(relative / path.relative_to(staging)))
        if destination.exists() and (not path.is_dir() or not destination.is_dir()):
            raise ValueError(f"Destination already exists: {destination.relative_to(storage.root)}")
    created_files, created_dirs = [], []

    def directory(path):
        if path.exists():
            return
        directory(path.parent)
        path.mkdir()
        created_dirs.append(path)

    try:
        directory(storage.path(str(relative)))
        for path in paths:
            destination = storage.path(str(relative / path.relative_to(staging)))
            if path.is_dir():
                directory(destination)
                continue
            directory(destination.parent)
            with path.open("rb") as source, destination.open("xb") as output:
                created_files.append(destination)
                copy_stream(source, output, storage)
                output.flush()
                os.fsync(output.fileno())
            path.unlink()  # Reclaim staging space as each file is published.
    except Exception:
        for path in reversed(created_files):
            path.unlink(missing_ok=True)
        for path in reversed(created_dirs):
            path.rmdir()
        raise
    return len(created_files)


def receive(stream, length, category, name, storage):
    """Receive exactly one raw file; a .zip expands beside its original path.

    Callers serialize uploads and prevent restart until this call completes.
    Temporary files (including ZIPs) are removed on success and normal failures.
    Nested archives are left as files; EPUBs and other ZIP-based formats are kept.
    """
    if category not in DESTINATIONS:
        raise ValueError("Choose music, data, or ebooks")
    path = safe_path(name)
    if length < 0:
        raise ValueError("Invalid upload size")
    storage.space(length)
    relative = PurePosixPath(DESTINATIONS[category]) / path.parent
    storage.path(str(relative / path.name))
    scratch = storage.path(".data_download/uploads")
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="upload-", dir=scratch) as temporary:
        temporary = Path(temporary)
        incoming = temporary / "incoming"
        with incoming.open("xb") as output:
            remaining = length
            while remaining:
                block = stream.read(min(CHUNK, remaining))
                if not block:
                    raise ValueError("Upload was interrupted; select the file again to retry")
                storage.space(len(block))
                output.write(block)
                remaining -= len(block)
        staging = temporary / "files"
        staging.mkdir()
        zipped = path.suffix.lower() == ".zip"
        try:
            if zipped:
                unpack(incoming, staging, storage)
                incoming.unlink()
            else:
                incoming.rename(staging / path.name)
            count = publish(staging, relative, storage)
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError, zlib.error) as exc:
            raise ValueError(f"Cannot extract ZIP: {exc}") from exc
    return {"ok": True, "files": count, "extracted": zipped,
            "destination": str(relative if zipped else relative / path.name)}
