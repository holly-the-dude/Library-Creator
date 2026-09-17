# Meshtastic on the Library Pi

One Podman container serves the **official Meshtastic web client through nginx
on port 8086**, and bridges HTTP to the Heltec's USB serial connection. It follows
the neighboring containers' `localhost/rasbase_master:latest` base (Debian 13
Trixie ARM64). A plain Debian Trixie base also works.

## Hardware and firmware

The supplied `HTIT-WSL_V3(Rev1.1).pdf` (pages 5–6 and 10) identifies the **Heltec
Wireless Stick Lite V3**: ESP32-S3FN8, SX1262, CP2102, USB-C. Meshtastic firmware
runs on that board; this container runs the Python client/CLI and web bridge.
`meshtasticd` is for Linux-native radio hardware and is not needed for this USB
device.

Before starting, attach the matching LoRa antenna. If the connected stick is a
**Heltec Wireless Stick Lite V3** still running factory firmware, the container
**installs Meshtastic firmware automatically** on first start (see
[Automatic firmware install](#automatic-firmware-install)). To flash a different
board or do it manually, use the [official web flasher](https://flasher.meshtastic.org/)
from a computer connected to its USB port, and stop anything using that serial
port while flashing.

Set the LoRa region for the physical radio/location with a Meshtastic client.
The HF model supports 863–928 MHz; the LF model covers 470–510 MHz. The container
**preserves the existing region, channels, keys, modem settings, and role** on a
radio that already has them. On a **freshly provisioned** radio (one that reports
region `UNSET`) it applies appliance defaults once, so a new stick comes up usable
without manual configuration:

- **LoRa region** is set to `LORA_REGION` (default `US`) **only when the region is
  `UNSET`**. An already-configured region is never overridden — set
  `LORA_REGION` to your region (for example `EU_868`) before first provisioning
  a non-US appliance, or empty to leave a new radio `UNSET`.
- **`device.serial_enabled`** (the web client's "Serial HAL Only" toggle) is
  turned on when it is off, because the Pi bridge talks to the radio over USB
  serial. Disable this assertion with `ENSURE_SERIAL_ENABLED=0`.

Each write is guarded on the current value, so a steady-state radio is never
rewritten. If `LORA_REGION` is empty and the radio is `UNSET`, configure the
region with a client before expecting mesh traffic.

## Automatic firmware install

The image bundles the pinned, checksum-verified Meshtastic firmware for the
**Heltec Wireless Stick Lite V3** (`firmware-heltec-wsl-v3`, release
`v2.7.26.54e0d8d`) and `esptool`. When the bridge starts and the Meshtastic
serial handshake fails, it probes the attached chip with esptool. Only if that
probe positively identifies an **ESP32-S3** (the exact chip this firmware
targets) does it install the firmware, then retry the handshake. It mirrors the
official `device-install.sh` sequence: full flash erase, factory image at `0x0`,
then the OTA stub and littlefs image at the offsets from the firmware metadata.

Safety and controls:

- A stick that already answers the Meshtastic protocol is **never touched**.
  Flashing only runs after a failed handshake.
- The board is identified by **two** bootloader-level signals before any write:
  the chip must be an **ESP32-S3** and its detected flash size must match the
  bundled firmware's partition scheme (**8MB**). Any other chip, a different
  flash size (for example a 16MB LilyGo ESP32-S3), or a port with nothing
  attached is left alone. Those boards must be flashed with the
  [official web flasher](https://flasher.meshtastic.org/).
- A radio that has ever worked here is normally **never probed or flashed
  again**. Once a handshake succeeds (`state.json`) or a flash completes
  (`flash.json`), later handshake timeouts are treated as transient and only
  retried. This matters because the esptool probe hard-resets the board over
  RTS; probing a working radio could knock it offline.
- The stored record can become **stale** — for example the board was wiped or
  swapped for a blank one, or the host volume persisted across a reinstall. So
  after a much longer run of consecutive failures (four times
  `FLASH_PROBE_AFTER`) the container runs a **read-only** blank-app probe: it
  resets the board and listens. Only if the board is confirmed to have no valid
  app image (its ROM loops `invalid header: 0xffffffff` and emits no Meshtastic
  frames) does it clear the stale record and reprovision. A working radio never
  reports that state, and a merely unreachable radio is probed at most once per
  session and left untouched.
- A genuinely first-seen board is only probed after several consecutive
  handshake failures (`FLASH_PROBE_AFTER`, default 3), so a one-off boot-timing
  miss never triggers a reset.
- Flashing is attempted **at most once** per detected unflashed board until a
  handshake succeeds, so a stuck device does not loop erase/write.
- Flashing **erases the board's entire flash and any prior settings**. Because
  the container preserves settings on radios that already run Meshtastic, this
  only affects a factory or non-Meshtastic stick.
- After a successful install the container writes `flash.json` (version, board,
  chip, flash size, timestamp) into the host volume as a record.
- Set `AUTO_FLASH=0` to disable automatic flashing entirely. `FLASH_PROBE_AFTER`
  tunes how many failures precede a probe. The build arg `FIRMWARE_VERSION`
  (with matching `FIRMWARE_SHA256`) and `FIRMWARE_DIR` control which images are
  bundled and where they are read from.

Rebuilding or restarting the container never reflashes a working radio; the
firmware lives on the stick's flash, not in the container.

### Errors do not trigger a reflash

Automatic flashing exists to provision a **brand-new, never-seen, factory
ESP32-S3 board**, not to react to errors on a radio the container already knows.
A handshake timeout is an ambiguous symptom: it is far more often caused by
serial-port contention (see the maps `GPS_PORT` note below), a USB line-state
wedge, an unplugged or mid-boot radio, or a stale device node than by bad
firmware. Reflashing on such an error would erase a healthy radio's region,
channels, and keys, and — because flashing itself hard-resets the board over
RTS — could provoke the next error and loop.

So for recurring errors on a known radio the container is deliberately
conservative: it keeps retrying the handshake every 10 seconds and reports the
error at `/bridge/status`, but never reflashes on its own. If you ever confirm
the flash is genuinely corrupt — the board's serial output shows the ROM
bootloader repeating `invalid header: 0xffffffff` (a blank/invalid app image)
rather than Meshtastic frames — reflash **manually and deliberately** with the
one-off CLI below or the [official web flasher](https://flasher.meshtastic.org/),
after first copying `config.yaml` since the erase removes all settings.

## Build and run on the Pi

Run these commands from this `containers/meshtastic` directory:

```bash
sudo podman build -t localhost/meshtastic:latest -f Containerfile .
sudo install -d -m 700 /Library/meshtastic
sudo podman run -d --name meshtastic --restart unless-stopped \
  --device '/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0:/dev/meshtastic:rwm' \
  -p 8086:8086 \
  -v /Library/meshtastic:/var/lib/meshtastic:Z \
  localhost/meshtastic:latest
```

If `rasbase_master` is unavailable, build with:

```bash
sudo podman build --build-arg BASE_IMAGE=docker.io/library/debian:trixie-slim \
  -t localhost/meshtastic:latest -f Containerfile .
```

The build uses the Pi's native architecture. The official web release is pinned
and checksum-verified; the Meshtastic Python package is pinned to `2.7.11`, and
`esptool` to `5.4.0`. The bundled Heltec firmware bundle is pinned by version and
SHA-256. Building requires internet access. Web assets are served locally afterward;
the official client's online map tiles and other online services still require
internet access. The existing `../build_pods.sh` and tar-export scripts discover
this container automatically.

Alternatively, after creating `/Library/meshtastic`, use `sudo podman compose up
-d --build` with the supplied `compose.yaml` (requires a Compose provider).
Compose accepts `BASE_IMAGE`, `MESHTASTIC_DEVICE`, `MESHTASTIC_DIR`, and
`DISCOVERY_SECONDS` environment overrides.

## Open the web client

1. Open **http://library:8086** (or `http://<Pi-IP>:8086`).
2. Allow the initial configuration download and 60-second discovery period to
   complete. Check `http://library:8086/bridge/status` for `"ready": true`.
3. Add an **HTTP** connection. Set the address to **`library:8086`** (or the same
   `<Pi-IP>:8086` used in the browser) and disable TLS/HTTPS for this connection.
4. Use the client to view nodes, send messages, and configure the radio.

Use **one active web client/tab at a time**. The USB radio has one configuration
stream and one receive queue. A second connection can consume the first one's
responses. The browser's **Serial** option targets the visiting computer's USB
ports; select **HTTP** to use the stick attached to the Pi.

Keep access on the trusted Library network: the official radio HTTP API permits
configuration and messaging without a login. Use the same hostname/IP for the
page and its HTTP connection; the bridge intentionally has no cross-origin API.

On plain LAN HTTP, the official client can fall back to in-memory browser
storage when its browser database requires a secure context. Do not rely on
browser message history surviving a reload. This does not affect settings saved
in the radio or the host volume. For durable browser storage, put the service
behind trusted HTTPS and use the same HTTPS origin for the HTTP radio connection.

## Node name and persistent data

The requested mapping is:

```text
/Library/meshtastic  ->  /var/lib/meshtastic
```

At startup or serial reconnection, the Python client downloads the radio's node database, then listens
for another `DISCOVERY_SECONDS` (default 60). It excludes its own node and checks
other nodes' long names without case sensitivity. It chooses `library0001`,
then `library0002`, and so on through `library9999` until a name is free. The
four-character short name is the same number, such as `0001`.

The chosen name is saved with the radio's node number. Restarts reuse it when
free; if another known node has claimed it, startup selects the next available
name. An existing valid `libraryNNNN` name on the same radio is also retained
when free. Names discovered later are checked on the next startup or reconnection.
This checks nodes **known to this radio**, including its stored node database;
Meshtastic has no global registry or atomic name reservation. Two new isolated
nodes can still choose the same name.

The host directory contains:

| File | Purpose |
| --- | --- |
| `state.json` | Chosen name and the radio identity it belongs to |
| `config.yaml` | Official CLI-compatible configuration backup from the most recent successful initialization |
| `nodes.json` | Node database snapshot used during that initialization |
| `flash.json` | Record of an automatic firmware install (version, board, chip, timestamp), when one occurred |

Files are written atomically with mode `0600`, outside the nginx web root. The
configuration backup contains channel keys and may contain a device private
key. Optional canned-message text/ringtones are included only when cached by
the Python client, rather than issuing extra potentially blocking requests.

Meshtastic stores configuration changes in the **stick's flash**. The startup
backup is refreshed when the container starts or the radio reconnects; it is not a live backup, and
the container never automatically overwrites a radio from that file. Copy the
backup elsewhere **before** connecting a replacement radio or starting after a
reset, since a successful startup refreshes the snapshot.

To explicitly restore a saved backup (with the normal container stopped):

```bash
sudo podman stop meshtastic
sudo podman run --rm \
  --device '/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0:/dev/meshtastic:rwm' \
  -v /Library/meshtastic:/var/lib/meshtastic:Z \
  --entrypoint meshtastic localhost/meshtastic:latest \
  --port /dev/meshtastic --configure /var/lib/meshtastic/config.yaml
sudo podman start meshtastic
```

Use the same one-off CLI pattern with `--info` or `--nodes` to inspect the radio.
Always stop the bridge first so two processes do not compete for its serial port.

To **manually** reflash a radio whose flash you have confirmed is corrupt (the
container never does this on its own — see
[Errors do not trigger a reflash](#errors-do-not-trigger-a-reflash)), copy
`config.yaml` elsewhere first, then run the bundled esptool against the stopped
bridge. This erases all settings:

```bash
sudo podman stop meshtastic
FW=/opt/meshtastic/firmware
V=2.7.26.54e0d8d
sudo podman run --rm \
  --device '/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0:/dev/meshtastic:rwm' \
  --entrypoint python3 localhost/meshtastic:latest -m esptool --port /dev/meshtastic erase-flash
for off_img in "0x0 firmware-heltec-wsl-v3-$V.factory.bin" \
               "0x340000 mt-esp32s3-ota.bin" \
               "0x670000 littlefs-heltec-wsl-v3-$V.bin"; do
  set -- $off_img
  sudo podman run --rm \
    --device '/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0:/dev/meshtastic:rwm' \
    --entrypoint python3 localhost/meshtastic:latest \
    -m esptool --port /dev/meshtastic --baud 460800 write-flash "$1" "$FW/$2"
done
sudo podman start meshtastic
```

## Operation and troubleshooting

### `Timed out waiting for connection completion`

This means the initial **USB device handshake** did not finish. It happens
before the discovery timer or automatic naming; nearby mesh nodes are not
required for the handshake. Increasing `DISCOVERY_SECONDS` cannot fix it.

The CP2102 device path can exist while the stick still runs its factory program.
On this Library stick, a serial boot inspection showed `WIFI Setup done` and
`Scan start...`, matching the [Heltec factory test](https://github.com/HelTecAutomation/Heltec_ESP32/blob/master/examples/Factory_Test/Wireless_Shell_V3_FactoryTest/Wireless_Shell_V3_FactoryTest.ino),
with no Meshtastic protocol responses. For a **Heltec Wireless Stick Lite V3**
the container installs `firmware-heltec-wsl-v3` automatically after this failed
handshake (see [Automatic firmware install](#automatic-firmware-install)); the
logs show the erase/write steps and the retry. A different board is left alone
and must be flashed with the [official web flasher](https://flasher.meshtastic.org/).
Flashing replaces the board's existing firmware; it lives on the stick, so
rebuilding the container does not reflash a working radio.

If Meshtastic is already installed, check that no other process holds the USB
port (`sudo fuser -v /dev/ttyUSB0`) and that **Serial Console** is enabled in the
radio's Security settings. Stop the container before testing the port with a
second client. An unset LoRa region affects radio traffic, not the USB handshake.

### Routine checks

- `sudo podman logs -f meshtastic` shows initialization, name selection, and
  connection errors without dumping keys or messages.
- `curl http://library:8086/health` checks nginx and the bridge are alive.
  `ready` reports radio availability separately, so an unplugged radio does not
  create a container restart loop.
- The bridge retries serial failures every 10 seconds. After USB unplug/replug,
  restart the container to refresh Podman's mapped device if the device number
  changed; recreate it if the by-id path changed.
- If the maps container also runs, set **its `GPS_PORT` to its actual GPS
  receiver's by-id path**. Its default GPS auto-detection can otherwise claim a
  lone generic serial device such as this CP2102. Stop that reader before using
  the Heltec. No `--privileged` or whole `/dev` mount is needed here.
- `DISCOVERY_SECONDS=120` gives the radio more time to hear nearby node names.
  Discovery is passive; quiet/offline nodes might not announce themselves.

Run the protocol and naming tests without radio hardware:

```bash
python3 -m venv /tmp/meshtastic-tests
/tmp/meshtastic-tests/bin/pip install 'meshtastic[cli]==2.7.11'
/tmp/meshtastic-tests/bin/python -m unittest discover -s tests -v
bash -n entrypoint.sh
```

## Upstream references

- [Heltec Wireless Stick Lite documentation](https://wiki.heltec.org/docs/devices/open-source-hardware/esp32-series/lora-32/wireless-stick-lite/)
- [Meshtastic Python client and CLI](https://github.com/meshtastic/python)
- [Meshtastic HTTP device API](https://meshtastic.org/docs/development/device/http-api/)
- [Official web client release v2.7.2](https://github.com/meshtastic/web/releases/tag/v2.7.2)
- [Web HTTP transport](https://github.com/meshtastic/web/blob/v2.7.2/packages/transport-http/src/transport.ts)
