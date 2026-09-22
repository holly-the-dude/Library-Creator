# Meshtastic offline TUI with a web terminal

Plug the radio into the **Raspberry Pi**, then open `http://<pi-ip>:8086`
on another computer, tablet, or phone. The browser displays a `dialog` TUI via
[ttyd](https://github.com/tsl0922/ttyd); `esptool` runs on the Pi and accesses
its USB serial ports. No browser Web Serial API or USB on the browser computer
is involved. Plain HTTP on a trusted local network works.

The image bundles firmware during the build. Running it and flashing bundled
firmware need no internet access. This implementation supports **ESP32-family
radios** with official partition manifests. nRF52/RP2040/other UF2 devices and
flash backup/restore are not implemented.

The container pins ttyd 1.7.7 using official SHA-256-checked binaries for ARM64,
ARMHF and AMD64. Its browser assets are embedded; Node/npm are not required.

## Library startup integration

Library startup exposes meshflash at **http://library:8086** (`8086:8086`).
Startup first checks USB devices for a
Meshtastic protocol response. If one responds, it starts the Meshtastic web
client instead; if none responds, it offers this setup terminal. The two
containers are stopped before selection and share the same web address.

After firmware installation finishes and the radio reboots, reboot the Pi or run
`sudo ansible-playbook /root/start_library.yml --tags mesh`. This stops setup,
checks the radio again and starts the Meshtastic client if it responds. Do not
run the command during a flash. The automatic switch happens on this startup
check, not while the TUI is open. Both container images must be loaded locally.

The standalone commands below continue to publish port 8086.

### Port configuration and upgrades

The Containerfile sets `PORT=8086`, and the entrypoint also defaults to 8086.
`start_library.yml`, `compose.yaml` and `meshlocal.sh` all publish host port 8086
to container port 8086. Compose additionally supports `MESHFLASH_BIND` to select
the host bind address.

When upgrading an older installation, rebuild the image, deploy the updated
launcher/playbook, and recreate the container after any flash has finished.
An existing container keeps its original port configuration; restarting it does
not apply a new mapping. If overriding `PORT` manually, the container side of the
published mapping must match ttyd's listening port.

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
[usage guide](../../../../docs/USAGE.md#using-meshtastic-and-radio-setup)
for the browser connection steps.

## Build and run on the Pi

Use rootful Podman (`sudo`) for USB hotplug permissions. If already logged in as
`root` (for example, `ssh root@library`), omit `sudo`. From this directory:

```sh
sudo podman build -t localhost/meshflash:latest -f Containerfile .
sudo podman run -d --name meshflash --restart unless-stopped \
  -p 8086:8086 \
  -v /dev:/host-dev:ro \
  --device-cgroup-rule='c 188:* rw' \
  --device-cgroup-rule='c 166:* rw' \
  localhost/meshflash:latest
```

**All three USB options are required:** the `/dev:/host-dev:ro` mount and both
`--device-cgroup-rule` options. Starting with only `-p 8086:8086` serves the web
terminal but gives it no access to the Pi's serial devices. The Containerfile
sets `SERIAL_ROOT=/host-dev`; host device access is configured at container
creation time, not during the image build. `compose.yaml` and `meshlocal.sh`
already include these USB options.

If Podman reports `device cgroup rules are not supported in rootless mode`, run
both build and run with `sudo` as shown above.

If a previous `meshflash` container exists, wait for any flash to finish, then
stop and remove it before repeating the complete `podman run` command above:

```sh
sudo podman stop meshflash
sudo podman rm meshflash
```

This also fixes an existing container created without USB access; no image
rebuild is needed for that fix. Restarting a container keeps its old mount and
device configuration. Building an image alone does not update an existing
container either. Use the same rootful
Podman image store for build and run. A standalone base can be selected with
`--build-arg BASE_IMAGE=docker.io/library/debian:trixie-slim`.

`/dev` is mounted at `/host-dev` so USB nodes can appear after startup or a radio
reset, while the terminal retains its own `/dev/pts`. The read-only mount
prevents directory changes; character devices can still be opened read/write.
The cgroup rules allow USB serial majors 188 (`ttyUSB`) and 166 (`ttyACM`),
without privileged mode. This setup targets Linux/Raspberry Pi, not a
Docker Desktop VM. Ports are displayed as `/host-dev/ttyUSB0`, etc.

Before using the flasher, stop the existing Meshtastic bridge if it is running:

```sh
sudo podman stop meshtastic
```

Also close serial monitors and any host service using the radio. The flasher
does not mount the Podman socket or automatically stop other containers. After
flashing, close the flasher session and restart the bridge when needed:

```sh
sudo podman start meshtastic
```

## Browser workflow

1. Open `http://<pi-ip>:8086`. Use arrows, Tab and Enter; Escape returns.
2. Select Update firmware or Erase & install firmware, then the Pi's USB port.
3. Select the exact board model and a bundled firmware version.
4. The flasher checks image checksums, detects the ESP32 chip and flash capacity,
   and refuses incompatible firmware. Confirm the displayed operation to flash.
5. After esptool finishes, use Device information to check Meshtastic boots.
   Reset the radio and reselect its USB port if necessary.

Chip detection cannot distinguish board models that share the same ESP32.
Select the correct physical board. An **update** writes only the application
partition and assumes the existing partition layout matches the release. A
**clean install** erases all firmware, settings and keys, then writes the merged
factory image plus the manifest's OTA/filesystem partitions. Every required
image is validated before erasing. Offsets follow the official release metadata
and [Meshtastic CLI workflow](https://meshtastic.org/docs/getting-started/flashing-firmware/esp32/cli-script/).

A shared `tmux` session keeps flashing alive if the browser disconnects. Reopen
the page to reconnect. Only one browser connection is accepted; SSH takes over
the same session. Do not stop/restart the container or unplug the radio during a
flash. Ctrl-C and tmux shell shortcuts are disabled in the TUI. Close the browser
or disconnect SSH to leave. Firmware write errors are shown without retrying or
claiming success; esptool verifies written data, while the separate Device
information action checks whether Meshtastic actually boots.

## Serial device troubleshooting

Compare what the Pi sees with what the container sees:

```sh
# On the Pi: identify USB devices and their current serial-port names.
ls -l /dev/serial/by-id/
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null

# Inside the running flasher: these should show the same serial devices.
sudo podman exec meshflash sh -c 'ls -ld /host-dev; ls -l /host-dev/ttyUSB* /host-dev/ttyACM* 2>/dev/null'
sudo podman inspect meshflash --format '{{json .Mounts}}'
```

- If the Pi sees the radio but `/host-dev` is missing in the container, recreate
  the container with the complete run command above. An empty mount list (`[]`)
  confirms the USB mount was omitted.
- If the ports appear but opening one reports a permission error, check that
  rootful Podman and both device cgroup rules were used.
- If the Pi itself has no serial port for the radio, check the USB data cable,
  power and boot mode. Container changes cannot create a missing host device.
- If the port is busy or Meshtastic does not respond, stop the Meshtastic bridge
  and other serial clients, then retry Device information in the TUI.

The menu lists USB serial devices, including devices that are not radios. During
troubleshooting on `library`, the TBEAM radio was `/dev/ttyACM1` (select
`/host-dev/ttyACM1` in the TUI), while `/dev/ttyACM0` was the u-blox GPS receiver.
**Do not assume these numbers are permanent:** check `/dev/serial/by-id/` after
reconnecting devices or rebooting. The radio's ID in that setup was
`usb-1a86_USB_Single_Serial_573C000510-if00`.

For manual ESP32 boot mode, hold BOOT/PRG, press and release RESET, then release
BOOT. If the port changes, return and select the new one. Default flash speed
is 115200; use `-e FLASH_BAUD=57600` for a slow cable.

## SSH fallback

SSH into the Pi, then attach to the same running TUI:

```sh
ssh user@pi-ip
sudo podman exec -it meshflash meshflash
```

This takes control from an attached browser without starting a second flasher.
If the browser service cannot be used at all, run only the TUI with no web port:

```sh
sudo podman run --rm -it --name meshflash-ssh \
  -v /dev:/host-dev:ro \
  --device-cgroup-rule='c 188:* rw' \
  --device-cgroup-rule='c 166:* rw' \
  --entrypoint python3 localhost/meshflash:latest /opt/meshflash/flasher.py
```

Stop the regular flasher before using this separate fallback. Keep SSH connected
until flashing finishes; this direct fallback has no persistent tmux session.

## Browser access control

By default the terminal is reachable without a password, suitable for the
Library's trusted offline LAN. Anyone who can reach port 8086 can operate the
flasher. Add `-e TTYD_CREDENTIAL='operator:your-password'` to enable browser login.
HTTP does not encrypt this password. For untrusted networks, bind the published
port to `127.0.0.1:8086:8086` and use an SSH tunnel (or a trusted HTTPS proxy):

```sh
ssh -N -L 8086:127.0.0.1:8086 user@pi-ip
```

Then open `http://localhost:8086`; the radio still plugs into the Pi.

## Offline firmware collection

The default build snapshots the latest stable/beta and latest alpha release,
with all ESP32 targets. To bundle only the Heltec Wireless Stick Lite V3 and
only stable/beta firmware:

```sh
sudo podman build --build-arg FIRMWARE_BOARDS=heltec-wsl-v3 \
  --build-arg FIRMWARE_ALPHA_COUNT=0 \
  -t localhost/meshflash:latest -f Containerfile .
```

`FIRMWARE_BOARDS` takes comma-separated official target names (e.g.
`heltec-wsl-v3,heltec-v3,tbeam`). `FIRMWARE_STABLE_COUNT` and
`FIRMWARE_ALPHA_COUNT` accept 0–4 each, with at least one release total. Older
releases lacking a root manifest are rejected instead of guessing flash layouts.
Missing targets, downloads, partitions or bad checksums fail the build.

Files live under `/opt/meshflash/firmware/<version>/<board>/`; `releases.json`
records channels and each version has `release_notes.md`. Only binaries and
manifests are downloaded, not web-flasher sources or ELF debug files. Rebuild
with `--no-cache` while online and recreate the container to refresh the
snapshot. The parent `build_pods.sh` / `create_tar_pods.sh` discover the container
and include bundled firmware in the saved image as before.

With a Compose provider installed, `sudo podman compose up -d --build` uses the
same USB setup. The Compose file accepts the firmware build variables,
`FLASH_BAUD`, `TTYD_CREDENTIAL`, and `MESHFLASH_BIND` (default `0.0.0.0`).

## Local checks

```sh
python3 -m unittest discover -s tests -v
```

Tests use synthetic firmware and mocked serial commands; a real radio is still
needed for end-to-end hardware verification.
