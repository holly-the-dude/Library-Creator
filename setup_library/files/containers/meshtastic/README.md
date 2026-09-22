# Meshtastic on the Library Pi

One Podman container serves the **official Meshtastic web client through nginx
on port 8086**, and bridges HTTP to the radio's USB serial connection. It follows
the neighboring containers' `localhost/rasbase_master:latest` base (Debian 13
Trixie ARM64). A plain Debian Trixie base also works.

## Hardware and firmware

This container connects to a USB radio already running Meshtastic, including
Heltec and LilyGo boards. It runs the official Python client and HTTP bridge;
firmware runs on the radio itself. It contains no esptool, firmware binaries or
automatic flashing code. Firmware installation and recovery belong to
[meshflash](../meshflash/README.md). Attach the correct LoRa antenna before use.

Set the LoRa region for the physical radio/location with a Meshtastic client.
The container **preserves the existing region, channels, keys, modem settings, and role** on a
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

## Automatic service selection at Library startup

`start_library.yml` scans `/dev/ttyUSB*` and `/dev/ttyACM*`, prefers stable
`/dev/serial/by-id/` names for mappings, and excludes identifiable GPS receivers
and the explicitly configured `gps_port`. Each candidate must complete a
Meshtastic configuration handshake. An ESP chip reported by the host's esptool
or a particular USB adapter VID is not sufficient evidence of Meshtastic.
Discovery runs in a temporary container using this image's Python client, with
no network, firmware writes, naming or configuration changes.

- One responding radio: stop meshflash and start meshtastic with that device
  mapped to `/dev/meshtastic`, serving `http://library:8086`.
- No responding radio (including no USB radio or a board with factory firmware):
  stop meshtastic and start meshflash at the same URL with USB hotplug access.
  Both services use `8086:8086`. Firmware installation requires confirmation
  in the TUI. See [flasher upgrades](../meshflash/README.md#port-configuration-and-upgrades)
  when replacing an older image.
- Multiple responding radios: stop with a message to set
  `-e meshtastic_device=/dev/serial/by-id/your-radio`. The override is still
  checked for a Meshtastic response.

Both images must be built/loaded locally. Rebuild the Meshtastic image when
updating from the old automatic-flashing implementation; discovery needs the
new `/opt/meshtastic/discover.py`. Copy the updated playbook to
`/root/start_library.yml` using the normal installer/deployment workflow.
Also redeploy the webserver image/configuration: its Meshtastic navigation
check now uses the shared host port, so the link appears for either service.

After flashing has finished and the board has rebooted, reboot the Pi or run:

```sh
sudo ansible-playbook /root/start_library.yml --tags mesh
```

This reruns only radio service selection. It stops both radio containers before
probing, then creates the selected one so a changed USB mapping is refreshed.
Do not run it during a flash. There is no background switch while the TUI is
open; selection happens at startup or when this command is run.

`meshtastic_probe_timeout` defaults to 12 seconds per candidate, plus up to five
seconds for client cleanup. Increase it for a radio that boots slowly. A
nonresponding/busy radio is offered setup, but is never erased automatically.
When a detected radio's bridge later fails, it reports the error and retries;
it does not switch to flashing or discard existing backups.

## Build both radio images

From the repository root, after preparing `rasbase_master`:

```sh
cd setup_library/files/containers
sudo ./build_pods.sh
sudo ./create_tar_pods.sh
```

The build script requires both radio Containerfiles and builds each as
`localhost/<folder>:latest`. The export script includes `meshtastic.tar` and
`meshflash.tar`, with the flasher's offline firmware inside its image. Run the
full build during maintenance, after any flash finishes, because it removes old
images before rebuilding. See the [developer guide](../../../../docs/DEVELOPERS.md#container-build-pipeline)
for the base-image and deployment workflow, and the
[usage guide](../../../../docs/USAGE.md#meshtastic-communications)
for the browser connection steps.

## Build and run on the Pi

For manual startup, identify the radio using `ls -l /dev/serial/by-id/` and set
`MESHTASTIC_DEVICE` to its full host path. On the tested Library Pi, the TBEAM
was `/dev/serial/by-id/usb-1a86_USB_Single_Serial_573C000510-if00`; the u-blox
receiver was GPS. Do not choose a port just because it is `ttyACM0`.
Run these commands from this `containers/meshtastic` directory after meshflash
has finished and stopped:

```bash
sudo podman build -t localhost/meshtastic:latest -f Containerfile .
sudo install -d -m 700 /Library/meshtastic
sudo podman run -d --name meshtastic --restart unless-stopped \
  --device "${MESHTASTIC_DEVICE:?Set the radio by-id path}:/dev/meshtastic:rwm" \
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
and checksum-verified; the Meshtastic Python package is pinned to `2.7.11`.
Building requires internet access. Web assets are served locally afterward;
the official client's online map tiles and other online services still require
internet access. The existing `../build_pods.sh` and tar-export scripts discover
this container automatically.

Alternatively, after creating `/Library/meshtastic`, use `sudo podman compose up
-d --build` with the supplied `compose.yaml` (requires a Compose provider).
Compose requires `MESHTASTIC_DEVICE` and accepts `BASE_IMAGE`, `MESHTASTIC_DIR`,
and `DISCOVERY_SECONDS` environment overrides.

## Open the web client

For everyday messaging, node lists and troubleshooting, use
[Meshtastic Communications in the Usage Guide](../../../../docs/USAGE.md#meshtastic-communications).
The steps below cover the Library-specific HTTP connection.

1. Open **http://library:8086** (or `http://<Pi-IP>:8086`).
2. Allow the initial configuration download and 60-second discovery period to
   complete. First startup can take a hot minute: the discovery period is in
   addition to connection time. Check
   [bridge status](http://10.1.1.1:8086/bridge/status) for `"ready": true`.
   Refresh to update; if `ready` is false, the `error` field explains whether
   the bridge is waiting for initialization or encountered a connection error.
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
  --device "${MESHTASTIC_DEVICE:?Set the radio by-id path}:/dev/meshtastic:rwm" \
  -v /Library/meshtastic:/var/lib/meshtastic:Z \
  --entrypoint meshtastic localhost/meshtastic:latest \
  --port /dev/meshtastic --configure /var/lib/meshtastic/config.yaml
sudo podman start meshtastic
```

Use the same one-off CLI pattern with `--info` or `--nodes` to inspect the radio.
Always stop the bridge first so two processes do not compete for its serial port.

To install or recover firmware, stop the bridge and use
[meshflash](../meshflash/README.md). Preserve your configuration backup before
erasing a radio. The Meshtastic container cannot flash firmware, even if legacy
`AUTO_FLASH` or `FIRMWARE_DIR` environment variables are still supplied.

## Operation and troubleshooting

### `Timed out waiting for connection completion`

This means the initial **USB device handshake** did not finish. It happens
before the discovery timer or automatic naming; nearby mesh nodes are not
required for the handshake. Increasing `DISCOVERY_SECONDS` cannot fix it.

A USB serial port can exist while the board runs a factory test program or
another firmware. If the radio does not answer Meshtastic, use meshflash to
select the correct board and install firmware. Handshake failures never trigger
an erase or write in this container.

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
  lone generic USB serial adapter. Stop that reader before using the radio.
  No `--privileged` or whole `/dev` mount is needed for the bridge itself.
- `DISCOVERY_SECONDS=120` gives the radio more time to hear nearby node names.
  Discovery is passive; quiet/offline nodes might not announce themselves.

Run the protocol and naming tests without radio hardware:

```bash
python3 -m venv /tmp/meshtastic-tests
/tmp/meshtastic-tests/bin/pip install 'meshtastic[cli]==2.7.11'
/tmp/meshtastic-tests/bin/python -m unittest discover -s tests -v
bash -n entrypoint.sh
```

The discovery tests include a simulated serial device speaking the Meshtastic
protocol. To exercise both startup branches with Ansible and fake Podman
commands, run from the repository root:

```sh
python3 -m unittest discover -s setup_library/tests -v
ansible-playbook --syntax-check setup_library/files/start_library.yml
```

## Upstream references

- [Heltec Wireless Stick Lite documentation](https://wiki.heltec.org/docs/devices/open-source-hardware/esp32-series/lora-32/wireless-stick-lite/)
- [Meshtastic Python client and CLI](https://github.com/meshtastic/python)
- [Meshtastic HTTP device API](https://meshtastic.org/docs/development/device/http-api/)
- [Official web client release v2.7.2](https://github.com/meshtastic/web/releases/tag/v2.7.2)
- [Web HTTP transport](https://github.com/meshtastic/web/blob/v2.7.2/packages/transport-http/src/transport.ts)
