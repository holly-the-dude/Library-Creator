#!/usr/bin/env python3
"""Install pinned Meshtastic firmware onto a supported ESP32-S3 stick.

This runs only when the Meshtastic serial handshake has already failed and an
esptool probe positively identifies the exact supported chip. A stick that
answers the Meshtastic protocol is never touched. The firmware images are the
official, checksum-verified files bundled in the container image; flashing
mirrors the upstream ``device-install.sh`` sequence (full erase, factory image
at 0x0, OTA stub and littlefs at their metadata offsets).

Flashing is deliberately conservative: it replaces the board's entire flash and
therefore erases any prior settings. It is enabled by ``AUTO_FLASH`` and guarded
so an unrelated or already-provisioned device is left alone.
"""

from contextlib import suppress
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import subprocess

LOG = logging.getLogger("meshtastic.flash")

# esptool 5.x uses dashed subcommands. This container pins 5.4.0.
ESPTOOL = ["python3", "-m", "esptool"]
FLASH_BAUD = "460800"
PROBE_TIMEOUT = 60
ERASE_TIMEOUT = 120
WRITE_TIMEOUT = 300
FACTORY_OFFSET = "0x0"


class FlashError(RuntimeError):
    """A supported board was detected but flashing could not complete."""


def _metadata_path(firmware_dir: Path):
    matches = sorted(firmware_dir.glob("firmware-*.mt.json"))
    return matches[0] if matches else None


def read_manifest(firmware_dir):
    """Return the bundled firmware manifest, or None when nothing is bundled.

    The manifest resolves the exact factory/OTA/littlefs filenames and the
    partition offsets straight from the official metadata, so a firmware bump
    only requires swapping the bundled files and their checksums.
    """
    firmware_dir = Path(firmware_dir)
    meta_path = _metadata_path(firmware_dir)
    if meta_path is None:
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlashError(f"Unreadable firmware metadata {meta_path.name}: {exc}")

    mcu = meta.get("mcu")
    version = meta.get("version", "")
    slug = meta.get("hwModelSlug", "")
    prog = meta_path.name[: -len(".mt.json")]  # firmware-<board>-<version>
    factory = firmware_dir / f"{prog}.factory.bin"
    littlefs = firmware_dir / f"littlefs-{prog[len('firmware-'):]}.bin"
    ota = firmware_dir / f"mt-{mcu}-ota.bin"

    def offset(subtype):
        for part in meta.get("part", []):
            if part.get("subtype") == subtype:
                return str(part.get("offset"))
        return None

    ota_offset = offset("ota_1")
    spiffs_offset = offset("spiffs")

    writes = [(FACTORY_OFFSET, factory)]
    if ota_offset and ota.is_file():
        writes.append((ota_offset, ota))
    if spiffs_offset and littlefs.is_file():
        writes.append((spiffs_offset, littlefs))

    missing = [str(path) for _, path in writes if not path.is_file()]
    if missing:
        raise FlashError("Bundled firmware files are missing: " + ", ".join(missing))

    return {
        "mcu": mcu,
        "version": version,
        "slug": slug,
        "flash_size": meta.get("partitionScheme"),
        "writes": writes,
        "metadata_path": meta_path,
    }


def _run(command, timeout):
    LOG.info("Running %s", " ".join(command))
    return subprocess.run(
        command, timeout=timeout, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True,
    )


def detect_chip(device):
    """Return (chip_name, flash_size) for the attached board, or (None, None).

    ``flash-id`` resets the ESP32 into its ROM download mode and reports the
    chip type and the detected flash size. A board that does not enter download
    mode (nothing attached, a bad cable, or a non-ESP device) yields
    ``(None, None)`` instead of raising. The flash size is a second signal used
    to distinguish the supported 8MB Heltec from other ESP32-S3 boards.
    """
    command = ESPTOOL + ["--port", device, "flash-id"]
    try:
        result = subprocess.run(
            command, timeout=PROBE_TIMEOUT, check=False,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.warning("esptool probe failed: %s", exc)
        return None, None
    output = result.stdout or ""
    if result.returncode != 0:
        LOG.warning("esptool probe returned %s: %s", result.returncode,
                    output.strip().splitlines()[-1:] or "")
        return None, None
    match = re.search(r"^\s*Chip is (\S+)", output, re.MULTILINE)
    if not match:
        match = re.search(r"Detecting chip type\.\.\.\s*(\S+)", output)
    chip = match.group(1) if match else None
    size = re.search(r"Detected flash size:\s*(\S+)", output)
    return chip, (size.group(1) if size else None)


def _normalize_size(value):
    """Canonicalize a flash-size string like '8MB' / '8 MB' -> '8mb'."""
    if not value:
        return None
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


# The ESP32-S3 ROM bootloader prints this repeatedly when the app partition is
# erased/invalid (it reads 0xffffffff where a valid image header should be). A
# board running Meshtastic never sits in this state, so it is a safe, positive
# signal that a "known-good" record is stale and the board is genuinely blank.
_BLANK_APP_MARKER = "invalid header: 0xffffffff"
_MESHTASTIC_FRAME = b"\x94\xc3"
BLANK_PROBE_SECONDS = 8


def app_is_blank(device):
    """Return True only if the board is confirmed running no valid app image.

    This is read-only: it hard-resets the board into its application (the same
    RTS reset esptool and the Meshtastic library already perform on open) and
    listens briefly. A blank/erased board's ROM loops ``invalid header:
    0xffffffff`` and emits no Meshtastic protobuf frames; a working radio emits
    frames and never the blank marker. Anything ambiguous (no output, an error,
    or any Meshtastic frame) returns False so a healthy or merely unreachable
    radio is never treated as blank.
    """
    # Reset into the app via esptool (tolerates a flaky CP2102 control channel).
    try:
        subprocess.run(
            ESPTOOL + ["--port", device, "--after", "hard-reset", "run"],
            timeout=PROBE_TIMEOUT, check=False,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.warning("Reset before blank-app probe failed: %s", exc)
        return False
    try:
        import serial  # local import: only needed for this probe
    except Exception:  # pragma: no cover - serial is always present at runtime
        return False
    try:
        stream = serial.Serial()
        stream.port = device
        stream.baudrate = 115200
        stream.timeout = 1
        # Do not toggle DTR/RTS here: we want to observe, not re-reset.
        stream.dtr = False
        stream.rts = False
        stream.open()
    except Exception as exc:
        LOG.warning("Blank-app probe could not open %s: %s", device, exc)
        return False
    data = bytearray()
    try:
        import time
        deadline = time.monotonic() + BLANK_PROBE_SECONDS
        while time.monotonic() < deadline:
            chunk = stream.read(1024)
            if chunk:
                data.extend(chunk)
    except Exception as exc:
        LOG.warning("Blank-app probe read failed: %s", exc)
        return False
    finally:
        with suppress(Exception):
            stream.close()
    if _MESHTASTIC_FRAME in bytes(data):
        return False  # the app is actually running; never treat as blank
    return _BLANK_APP_MARKER.encode() in bytes(data)


def chip_matches(chip_name, mcu):
    """True when esptool's chip string is the supported MCU family (esp32s3)."""
    if not chip_name or not mcu:
        return False
    normalized = re.sub(r"[^a-z0-9]", "", chip_name.lower())
    return normalized.startswith(re.sub(r"[^a-z0-9]", "", mcu.lower()))


def flash_firmware(device, manifest):
    """Erase then write the bundled images, mirroring device-install.sh."""
    _run(ESPTOOL + ["--port", device, "erase-flash"], ERASE_TIMEOUT)
    for offset, path in manifest["writes"]:
        _run(
            ESPTOOL + ["--port", device, "--baud", FLASH_BAUD,
                       "write-flash", offset, str(path)],
            WRITE_TIMEOUT,
        )


def _record(data_dir, manifest, chip, flash_size):
    """Persist a small marker so operators can see what was flashed and when."""
    if not data_dir:
        return
    record = {
        "flashed_at": datetime.now(timezone.utc).isoformat(),
        "version": manifest["version"],
        "board": manifest["slug"],
        "chip": chip,
        "flash_size": flash_size,
    }
    with suppress(OSError):
        data_dir = Path(data_dir)
        data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = data_dir / "flash.json"
        target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        os.chmod(target, 0o600)


def auto_flash(device, firmware_dir, data_dir=None, enabled=True):
    """Flash a supported unflashed board; return True only when it flashed.

    Call this after the Meshtastic handshake has failed. The bundled image is
    board-specific (Heltec Wireless Stick Lite V3), so flashing is guarded by
    two bootloader-level signals that together identify that board and reject
    other ESP32-S3 devices (for example a 16MB LilyGo):

    * the chip family must be the supported MCU (esp32s3), and
    * the detected flash size must match the firmware's partition scheme (8MB).

    It declines quietly (returns False) when auto-flash is disabled, no firmware
    is bundled, nothing is attached, or either signal does not match. It raises
    FlashError when a fully matching board is present but esptool fails, so the
    caller can surface the error and retry later rather than looping silently.
    """
    if not enabled:
        LOG.info("Auto-flash disabled; leaving the board untouched")
        return False
    manifest = read_manifest(firmware_dir)
    if manifest is None:
        LOG.info("No bundled firmware; cannot auto-flash")
        return False
    chip, flash_size = detect_chip(device)
    if chip is None:
        LOG.info("No ESP chip detected on %s; not a flashable board", device)
        return False
    if not chip_matches(chip, manifest["mcu"]):
        LOG.warning("Detected %s does not match supported %s; refusing to flash. "
                    "A different board must be flashed with the web flasher.",
                    chip, manifest["mcu"])
        return False
    expected_size = _normalize_size(manifest["flash_size"])
    detected_size = _normalize_size(flash_size)
    if expected_size and detected_size != expected_size:
        LOG.warning("Detected %s with %s flash, but the bundled %s firmware "
                    "targets a %s board; refusing to flash a different ESP32-S3 "
                    "device. Use the web flasher for this board.",
                    chip, flash_size or "unknown", manifest["slug"],
                    manifest["flash_size"])
        return False
    LOG.warning("Detected unflashed %s (%s, %s flash). Installing Meshtastic %s; "
                "this erases the board's existing firmware and settings.",
                chip, manifest["slug"], flash_size or "unknown", manifest["version"])
    try:
        flash_firmware(device, manifest)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        detail = getattr(exc, "output", "") or ""
        raise FlashError(f"esptool failed while flashing {manifest['slug']}: "
                         f"{exc}\n{detail}".strip()) from exc
    _record(data_dir, manifest, chip, flash_size)
    LOG.info("Flashed Meshtastic %s onto %s (%s)", manifest["version"],
             manifest["slug"], chip)
    return True
