#!/usr/bin/env python3
"""Offline, manifest-driven ESP32 flasher. Run inside the shared tmux session."""

from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys


def safe_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ValueError(f"Unsafe firmware filename: {name!r}")
    return name


def verify_file(path, entry):
    content = path.read_bytes()
    if len(content) != entry["bytes"] or hashlib.md5(content).hexdigest() != entry["md5"]:
        raise ValueError(f"Firmware checksum mismatch: {path.name}")


def number(value):
    return int(value, 0) if isinstance(value, str) else int(value)


@dataclass
class Manifest:
    path: Path
    data: dict

    @property
    def chip(self):
        return self.data["mcu"]

    @property
    def board(self):
        return self.data["platformioTarget"]

    @property
    def title(self):
        return self.data.get("displayName", self.board)

    def plan(self, mode):
        """Validate every write before erase; offsets come from official metadata."""
        if mode not in ("install", "update"):
            raise ValueError("Unknown flash mode")
        parts = {p["name"]: p for p in self.data["part"]}
        app = next(p for p in parts.values() if p["subtype"] == "ota_0")
        # Release files use canonical app0/app1 even when the partition table
        # calls these app/flashApp. Resolve those aliases by OTA subtype.
        aliases = {"app0": "ota_0", "app1": "ota_1", "spiffs": "spiffs"}

        def partition(entry):
            name = entry.get("part_name")
            if name is None:
                return None
            if name in parts:
                return parts[name]
            return next(p for p in parts.values() if p["subtype"] == aliases[name])

        entries = [e for e in self.data["files"] if e["name"].endswith(".bin")]
        if mode == "update":
            entries = [e for e in entries if partition(e) == app]
            if len(entries) != 1:
                raise ValueError("Expected exactly one application update image")
        else:
            factory = [e for e in entries if e["name"].endswith(".factory.bin")]
            if len(factory) != 1:
                raise ValueError("Expected exactly one factory image")
            entries = factory + [e for e in entries if partition(e) not in (None, app)]
            # A declared OTA/filesystem partition must have a corresponding image.
            for part in parts.values():
                if part["subtype"] in ("ota_1", "spiffs") and not any(
                    partition(e) == part for e in entries
                ):
                    raise ValueError(f"Missing image for partition {part['name']}")
        writes = []
        for entry in entries:
            path = self.path.parent / safe_name(entry["name"])
            verify_file(path, entry)
            if entry["name"].endswith(".factory.bin"):
                offset = 0  # Meshtastic's merged factory image (device-install.sh).
                limit = number(app["offset"]) + number(app["size"])
            else:
                part = partition(entry)
                offset, limit = number(part["offset"]), number(part["size"])
            if offset < 0 or entry["bytes"] <= 0 or entry["bytes"] > limit:
                raise ValueError(f"Invalid image size or partition offset: {path.name}")
            writes.append((offset, path))
        writes.sort()
        for (offset, path), (next_offset, _) in zip(writes, writes[1:]):
            if offset + path.stat().st_size > next_offset:
                raise ValueError("Overlapping firmware images")
        return writes


def load_manifest(path):
    data = json.loads(path.read_text())
    if not re.fullmatch(r"esp32(?:s[23]|c[236]|h2)?", data["mcu"]):
        raise ValueError(f"Unsupported MCU: {data['mcu']}")
    safe_name(data["platformioTarget"])
    safe_name(data["version"])
    return Manifest(path, data)


def parse_probe(output):
    chip = re.search(r"(?:Chip (?:is|type:)\s*|Detecting chip type\.*\s*)(ESP32(?:-[A-Z][0-9]+)?)\b", output)
    size = re.search(r"Detected flash size:\s*(\d+)\s*MB", output)
    if not chip or not size:
        raise ValueError("Could not identify ESP32 chip and flash size. Check BOOT/RESET and USB cable.")
    return chip[1].lower().replace("-", ""), int(size[1]) * 1024 * 1024


def check_device(manifest, chip, capacity, writes):
    if chip != manifest.chip:
        raise ValueError(f"Chip mismatch: radio is {chip}, firmware requires {manifest.chip}")
    required = max(number(p["offset"]) + number(p["size"]) for p in manifest.data["part"])
    if required > capacity or any(offset + path.stat().st_size > capacity for offset, path in writes):
        raise ValueError("Firmware layout is larger than the device's detected flash")


def dialog(kind, prompt, options=()):
    command = ["dialog", "--stdout", "--title", "Meshtastic Offline Flasher"]
    if kind == "yesno":
        command += ["--defaultno"]
    command += [f"--{kind}", prompt, "0", "0"]
    if kind == "menu":
        command += ["0", *[item for pair in options for item in pair]]
    result = subprocess.run(command, stdout=subprocess.PIPE, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def pause(message):
    print(f"\n{message}\n\nPress Enter to return to the menu.", flush=True)
    try:
        input()
    except EOFError:
        pass


def esptool(port, baud, *args, capture=False):
    command = [sys.executable, "-m", "esptool", "--port", str(port), "--baud", baud, *args]
    return subprocess.run(command, check=True, text=True, timeout=900,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.STDOUT if capture else None)


def flash(manifest, mode, port, baud):
    writes = manifest.plan(mode)
    print("Checking chip and flash size...", flush=True)
    probe = esptool(port, baud, "flash-id", capture=True)
    print(probe.stdout, flush=True)
    chip, capacity = parse_probe(probe.stdout)
    check_device(manifest, chip, capacity, writes)
    detail = ("ERASE ALL settings, keys and firmware, then install." if mode == "install" else
              "Update application only. Existing partition layout must match; back up settings first.")
    prompt = (f"Device: {port}\nChip: {chip}, {capacity // 1048576} MB\n"
              f"Board: {manifest.title} ({manifest.board})\nVersion: {manifest.data['version']}\n\n"
              f"{detail}\n\nChip detection cannot identify the exact board. Confirm the board model "
              "and keep the USB device connected. Proceed?")
    if dialog("yesno", prompt) is None:
        return
    # Recheck files before any destructive command, including after confirmation.
    writes = manifest.plan(mode)
    subprocess.run(["clear"], check=False)
    if mode == "install":
        esptool(port, baud, "erase-flash")
    args = [value for offset, path in writes for value in (hex(offset), str(path))]
    esptool(port, baud, "write-flash", *args)
    pause("Flash completed; esptool verified the written data. Reset the radio if needed. "
          "Use Device information to check that Meshtastic boots (USB port may change).")


def main():
    # Protect against a second manually launched TUI as well as browser sessions.
    lock = open("/tmp/meshflash.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Flasher already running. Attach with: meshflash")
        return
    # Ctrl-C/Ctrl-Z must not interrupt an erase/write or expose an underlying shell.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTSTP, signal.SIG_IGN)
    root = Path(os.environ.get("FIRMWARE_DIR", "/opt/meshflash/firmware"))
    devices = Path(os.environ.get("SERIAL_ROOT", "/host-dev"))
    baud = os.environ.get("FLASH_BAUD", "115200")
    if baud not in ("57600", "115200", "230400", "460800", "921600"):
        raise ValueError("Unsupported FLASH_BAUD")
    while True:
        try:
            action = dialog("menu", "Plug the radio into the Raspberry Pi.\nStop other services using its USB port.\n"
                            "ESP32 devices only; arrows/Tab/Enter select, Escape returns.", [
                                ("update", "Update firmware"), ("install", "Erase & install firmware"),
                                ("info", "Device information (Meshtastic CLI)"), ("help", "Connection help")])
            if action is None:
                continue  # Close the browser/SSH client to disconnect; keep session alive.
            if action == "help":
                dialog("msgbox", "Radio USB connects to the Pi, not the browser computer.\n\n"
                       "Stop the meshtastic bridge / serial monitor before flashing.\n"
                       "For ESP32 boot mode: hold BOOT, press/release RESET, release BOOT.\n"
                       "If USB reconnects as another port, return and select it again.\n\n"
                       "Closing the browser leaves a flash running. Reopen to reconnect.\n"
                       "Never stop the container or unplug the radio during a flash.")
                continue
            ports = sorted(p for pattern in ("ttyUSB*", "ttyACM*") for p in devices.glob(pattern) if p.is_char_device())
            if not ports:
                dialog("msgbox", "No USB serial devices found on the Pi.\nConnect a data-capable USB cable, "
                       "check container USB access, then retry. nRF52/RP2040 UF2 boards are not supported.")
                continue
            selected = dialog("menu", "Select the radio's USB port on the Pi", [(str(p), p.name) for p in ports])
            if selected is None:
                continue
            port = Path(selected)
            if action == "info":
                subprocess.run(["clear"], check=False)
                subprocess.run(["meshtastic", "--port", str(port), "--info"], check=True, timeout=60)
                pause("Meshtastic responded.")
                continue
            manifests = [load_manifest(p) for p in sorted(root.rglob("*.mt.json"))]
            boards = {m.board: m.title for m in manifests}
            if not boards:
                raise ValueError("No bundled firmware manifests found")
            board = dialog("menu", "Select the exact board model (not just the chip)", sorted(boards.items()))
            if board is None:
                continue
            candidates = [m for m in manifests if m.board == board]
            releases = json.loads((root / "releases.json").read_text())
            titles = {r["version"]: r["title"] for r in releases}
            index = dialog("menu", "Select bundled firmware version", [
                (str(i), titles.get(m.data["version"], m.data["version"])) for i, m in enumerate(candidates)])
            if index is None:
                continue
            subprocess.run(["clear"], check=False)
            flash(candidates[int(index)], action, port, baud)
        except (ValueError, KeyError, StopIteration, OSError, subprocess.SubprocessError) as exc:
            subprocess.run(["clear"], check=False)
            print(f"Operation failed: {exc}", flush=True)
            if isinstance(exc, subprocess.CalledProcessError) and exc.stdout:
                print(exc.stdout)
            pause("No automatic retry. Check the selected board, USB port, cable and BOOT/RESET; "
                  "stop other serial services before retrying.")


if __name__ == "__main__":
    main()
