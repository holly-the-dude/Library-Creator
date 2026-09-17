"""Name the attached radio and save a private, read-only configuration backup.

The radio's own node database is the source for name collision detection. It
cannot discover every node worldwide, or reserve names against simultaneous
startups. Configuration remains authoritative on the radio; backups are never
restored automatically.
"""

from contextlib import contextmanager, suppress
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import re
import tempfile
import time

from meshtastic.__main__ import export_config
from meshtastic.protobuf import config_pb2
from meshtastic.serial_interface import SerialInterface


NAME_PATTERN = re.compile(r"library([0-9]{4})", re.IGNORECASE)
CONNECT_TIMEOUT = 30
LOG = logging.getLogger("meshtastic.bootstrap")


def _env_flag(name, default=True):
    """Read a boolean-ish environment flag; default when unset/empty."""
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() not in ("0", "false", "no", "off")


def _provision_defaults(interface):
    """Apply appliance defaults to a freshly-provisioned radio, conservatively.

    Two settings are asserted so a brand-new or reflashed board comes up usable
    without manual configuration:

    * LoRa region: set to ``LORA_REGION`` (default ``US``) ONLY when the radio
      currently reports ``UNSET``. An already-configured region is never
      changed, so a radio deliberately set to another region is preserved.
    * ``device.serial_enabled`` ("Serial HAL Only" in the web client): the Pi
      bridge talks to the radio over USB serial, so this must be on. It is set
      to true only when it is not already true, avoiding needless writes.

    Each write is guarded on the current value so a steady-state radio is left
    untouched (no write, no reconnect). Returns True when anything was written.
    """
    changed = False
    local = interface.localNode
    config = local.localConfig

    # --- LoRa region (only when UNSET) ---
    region_name = os.environ.get("LORA_REGION", "US").strip()
    if region_name and config.lora.region == config_pb2.Config.LoRaConfig.UNSET:
        try:
            region_value = config_pb2.Config.LoRaConfig.RegionCode.Value(region_name.upper())
        except ValueError:
            LOG.warning("Ignoring invalid LORA_REGION=%r; leaving region UNSET",
                        region_name)
        else:
            LOG.info("Region is UNSET; setting it to %s for this new radio",
                     region_name.upper())
            config.lora.region = region_value
            local.writeConfig("lora")
            changed = True

    # --- serial_enabled (must be on for the USB bridge) ---
    if _env_flag("ENSURE_SERIAL_ENABLED", True) and not config.device.serial_enabled:
        LOG.info("Enabling device.serial_enabled (Serial HAL) for the USB bridge")
        config.device.serial_enabled = True
        local.writeConfig("device")
        changed = True

    return changed


def valid_name(value):
    """Return a canonical library name, or None for another owner name."""
    if not isinstance(value, str):
        return None
    match = NAME_PATTERN.fullmatch(value)
    if match and 1 <= int(match[1]) <= 9999:
        return value.casefold()
    return None


def choose_name(nodes, node_num, current_name, state):
    """Reuse this radio's available name, otherwise pick the lowest free suffix."""
    occupied = {
        str(node.get("user", {}).get("longName", "")).casefold()
        for number, node in nodes.items()
        if number != node_num
    }
    preferred = None
    if state.get("node_num") == node_num:
        preferred = valid_name(state.get("long_name"))
    # State for a different radio must never transfer its name to this radio.
    if preferred is None:
        preferred = valid_name(current_name)
    if preferred is not None and preferred not in occupied:
        return preferred
    for suffix in range(1, 10000):
        candidate = f"library{suffix:04d}"
        if candidate not in occupied:
            return candidate
    raise RuntimeError("All library0001 through library9999 names are in use")


def atomic_write(path, text):
    """Publish a complete UTF-8 file with mode 0600, including on replacement."""
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary)


def _read_state(path):
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeError, json.JSONDecodeError):
        return {}
    return state if isinstance(state, dict) else {}


@contextmanager
def _radio(device):
    # Construct without connecting so even a failed handshake leaves us a
    # reference that can be closed. Protocol and node DB loading stay enabled.
    interface = SerialInterface(
        devPath=device, connectNow=False, timeout=CONNECT_TIMEOUT,
    )
    try:
        interface.connect()
        interface.waitForConfig()
        yield interface
    finally:
        try:
            interface.close()
        finally:
            # SerialInterface.close() flushes before closing. An unplug during
            # that flush must still release the underlying serial descriptor.
            stream = getattr(interface, "stream", None)
            if stream is not None:
                with suppress(Exception):
                    stream.close()
            timer = getattr(interface, "heartbeatTimer", None)
            if timer is not None:
                timer.cancel()


def _node_snapshot(interface):
    # Copy the dictionary before iterating: the library's reader can add nodes.
    return {
        number: {"user": dict(node.get("user", {})),
                 "lastHeard": node.get("lastHeard")}
        for number, node in (interface.nodesByNum or {}).copy().items()
    }


def _identity(interface):
    node_num = interface.localNode.nodeNum
    info = interface.getMyNodeInfo()
    if not isinstance(node_num, int) or node_num <= 0 or not info:
        raise RuntimeError("Radio did not return its local node information")
    return node_num, dict(info.get("user", {}))


class _ExportSnapshot:
    """Use the official YAML exporter without unbounded optional text queries.

    Meshtastic 2.7.11 get_canned_message()/get_ringtone() can wait forever on
    firmware that does not answer. All core config, channels and owner data are
    already loaded by the handshake. Optional strings are exported only when
    they were cached; the original interface is never modified.
    """

    def __init__(self, interface):
        self.interface = interface
        self.localNode = interface.localNode

    def __getattr__(self, name):
        return getattr(self.interface, name)

    def getCannedMessage(self):
        return self.localNode.cannedPluginMessage

    def getRingtone(self):
        return self.localNode.ringtone


def _save_snapshot(interface, data_dir, long_name, changed, nodes):
    node_num, user = _identity(interface)
    region_number = interface.localNode.localConfig.lora.region
    try:
        region = config_pb2.Config.LoRaConfig.RegionCode.Name(region_number)
    except ValueError:
        region = str(region_number)
    metadata = {
        "node_num": node_num,
        "node_id": user.get("id", f"!{node_num:08x}"),
        "long_name": long_name,
        "short_name": long_name[-4:],
        "region": region,
        "firmware_version": getattr(interface.metadata, "firmware_version", ""),
        "discovered_nodes": sum(number != node_num for number in nodes),
        "name_changed": changed,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    # This can contain channel keys and private security config. Keep it out of
    # stdout, status responses and the nginx document root.
    config_text = export_config(_ExportSnapshot(interface))
    atomic_write(data_dir / "config.yaml", config_text)
    # Explicit fields exclude library-internal adminSessionPassKey and any
    # future additions to its raw node dictionaries.
    visible_nodes = [
        {"node_num": number,
         "node_id": node["user"].get("id", f"!{number:08x}"),
         "long_name": node["user"].get("longName", ""),
         "short_name": node["user"].get("shortName", ""),
         "last_heard": node["lastHeard"]}
        for number, node in sorted(nodes.items())
    ]
    atomic_write(data_dir / "nodes.json", json.dumps(visible_nodes, indent=2) + "\n")
    state = {"version": 1, "node_num": node_num, "long_name": long_name,
             "short_name": long_name[-4:]}
    atomic_write(data_dir / "state.json", json.dumps(state, indent=2) + "\n")
    if region == "UNSET":
        LOG.warning("Radio region is UNSET; choose the correct region in the web client")
    else:
        LOG.info("Radio region: %s", region)
    return metadata


def bootstrap_radio(device: str, data_dir: Path, discovery_seconds: float):
    """Discover names, configure this radio if necessary, back it up, then close.

    Raises on a failed name write or backup. Each file is replaced atomically;
    the files are not a multi-file transaction. The caller may retry; an
    already-correct radio is never rewritten.
    Region, channels, licensing flags and all unrelated settings are preserved.
    """
    if not device:
        raise ValueError("A serial device path is required")
    if not math.isfinite(discovery_seconds) or discovery_seconds < 0:
        raise ValueError("Discovery seconds must be finite and nonnegative")
    data_dir = Path(data_dir)
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = _read_state(data_dir / "state.json")
    with _radio(device) as interface:
        if discovery_seconds:
            time.sleep(discovery_seconds)
        node_num, user = _identity(interface)
        nodes = _node_snapshot(interface)
        long_name = choose_name(nodes, node_num, user.get("longName"), state)
        LOG.info("Selected %s (%s); checked %d other known nodes", long_name,
                 long_name[-4:], sum(number != node_num for number in nodes))
        # Assert appliance defaults (region/serial) on a new or reflashed radio.
        # Guarded internally so a steady-state radio is not rewritten.
        provisioned = _provision_defaults(interface)
        name_changed = (user.get("longName") != long_name or
                        user.get("shortName") != long_name[-4:])
        if not name_changed and not provisioned:
            return _save_snapshot(interface, data_dir, long_name, False, nodes)
        if name_changed:
            interface.localNode.setOwner(
                long_name=long_name, short_name=long_name[-4:],
                is_licensed=bool(user.get("isLicensed", False)),
                is_unmessagable=bool(user.get("isUnmessagable", False)),
            )
        # Local writes have no ACK callback. Allow the device to commit before
        # reconnecting and checking a fresh config/node DB download.
        time.sleep(1)
    with _radio(device) as interface:
        verified_num, user = _identity(interface)
        if name_changed and (verified_num != node_num or
                             user.get("longName") != long_name or
                             user.get("shortName") != long_name[-4:]):
            raise RuntimeError("Radio did not confirm the requested owner name")
        nodes.update(_node_snapshot(interface))
        return _save_snapshot(interface, data_dir, long_name, name_changed, nodes)
