# StreetZim reader with Library USB GPS

An optional reader for downloaded [StreetZim](https://github.com/jasontitus/streetzim)
archives. The Library homepage's **Maps** menu offers **OpenStreetMap** and
**StreetZim**. The boot playbook starts StreetZim when its image is installed;
StreetZim owns the USB GPS and shares its feed with OpenStreetMap.

| Setting | Default |
| --- | --- |
| Container name / image | `street_zim` / `localhost/street_zim:latest` |
| Podman network / address | existing `podman` bridge / `10.88.0.216` |
| Published port | `8093` |
| Hotspot URL | `http://10.1.1.1:8093` |
| Local development URL | `http://localhost:8093` |
| Archive folder | shared `/Library/wiki`, mounted read-only at `/data` |
| GPS source at Library startup | auto-detected USB receiver; shared with OpenStreetMap |
| Standalone image default | relay from `http://10.88.0.212:8080/api/gps` |

The address and port were unassigned in the repository and available in the
development Podman runtime when added. `manage.py start` checks the selected
host's port and Podman address before starting; the target Pi may differ.
Use rootful Podman on the Library appliance, matching its existing services.

## Build and run

From the `street_zim` folder on the Pi, build with Podman:

```bash
sudo podman build --format docker -t localhost/street_zim:latest -f Containerfile .
```

`--format docker` selects the image format so Podman preserves the image's
health check; Docker is not required. The parent `build_pods.sh` also uses this
format when building StreetZim and the other images.

The image uses `ARG BASE_IMAGE=localhost/rasbase_master:latest` and
`FROM ${BASE_IMAGE}`, matching the other Library images. To select another
Library base, add `--build-arg BASE_IMAGE=localhost/YOUR_BASE:latest`.

With the USB mounted and its ZIM files available at `/Library/wiki`, this
standalone command gives StreetZim ownership of the auto-detected USB GPS.
Stop any existing serial GPS reader first. To share with OpenStreetMap, use its
`GPS_UPSTREAM` setting as described in the integration section below.

```bash
sudo podman run -d \
  --name street_zim \
  --restart unless-stopped \
  --network podman \
  --ip 10.88.0.216 \
  -p 8093:8093 \
  -v /Library/wiki:/data:ro \
  --privileged -v /dev:/dev \
  -e GPS_MODE=serial \
  -e GPS_BAUD=9600 \
  localhost/street_zim:latest
```

Open **Maps → StreetZim** or **http://10.1.1.1:8093** from the hotspot. The command
reads the USB archives without modifying them. If this
container already exists and is stopped, use `sudo podman start street_zim`.
Rebuilding the image does not update an existing container; recreate only
`street_zim` to use the new image or change its mount/settings.

The Python helper is optional, with address and port checks before starting.
Its default start command uses the older Maps-owned relay setup; pass
`--gps-device` as described below to select a dedicated receiver:

```bash
sudo python3 manage.py build
sudo python3 manage.py start
```

No Compose installation is required. Build installs packages into your Library
base image; the running reader uses local assets and archives.

Open **Downloads → StreetZim maps**, select a region from the
[StreetZim catalog](https://streetzim.web.app/), and download it. The downloader
checks its exact size and Internet Archive MD5, then saves the complete `.zim`
alongside the other ZIM files in `/Library/wiki/`. Then run:

```bash
sudo podman restart street_zim
```

Open the URL above and select **Open map library**. The private Kiwix catalog is
rebuilt at startup; adding/removing files requires a restart. An empty folder
is supported and shows setup instructions. Invalid archives fail startup with
an error in `podman logs street_zim`; partial downloads ending in `.part` and
macOS `._*.zim` metadata sidecars are ignored. Sidecars are not map archives;
they can remain on the USB without being loaded or modified. Use complete,
unsplit `.zim` files directly inside the folder.

StreetZim and the existing Kiwix reader share the same archive files. StreetZim
builds its own catalog inside the container and does not change the shared
`wiki.xml`, archive files, or their SELinux labels. All complete `.zim` files
in the shared folder appear in its catalog, including non-map collections;
GPS integration applies to compatible StreetZim maps.

The shared directory must already exist. To use its location on a development
host where the Library drive is mounted one level deeper:

```bash
sudo env STREET_ZIM_DIR=/Library/Library/wiki python3 manage.py start
```

Select the data folder before first start. The script refuses to replace an
existing container. To change mounts, IP or GPS mode, explicitly stop/remove
only `street_zim`, then start it again; removing the container does not delete
your archive directory. To use the optional isolated test folder instead, set
`STREET_ZIM_DIR` to the absolute path of `street_zim/zims`. Not every map ZIM
has the same viewer, search or routing features.

Optional helper/Compose environment settings: `STREET_ZIM_DIR`, `STREET_ZIM_PORT`,
`STREET_ZIM_IP`, `STREET_ZIM_NETWORK`, `GPS_UPSTREAM` (an HTTP origin, without
`/api/gps`). Override them with `sudo env NAME=value ...` when using sudo.
For a direct `podman run`, edit the corresponding `-v`, `-p`, `--ip`,
`--network`, or `-e` arguments instead.

If Compose is available, the equivalent is:

```bash
sudo podman compose up -d --build
```

Compose uses the existing `podman` network too; it does not run the startup
script's address preflight. Its default GPS mode is relay.

## Install the integrated Maps menu and startup

From `setup_library/files/containers`, rebuild the four affected images:

```bash
for service in street_zim library_maps webserver data_download; do
  sudo podman build --format docker -t "localhost/$service:latest" \
    -f "$service/Containerfile" "$service"
done
```

Install the updated `setup_library/files/start_library.yml` as
`/root/start_library.yml` on the appliance, then restart the Library through its
normal restart control. Rebuilding images alone does not replace running
containers. The boot playbook recreates the affected services and regenerates
the homepage. When distributing saved images, regenerate their image tar files
too.

Startup stops the old Maps reader before giving StreetZim the receiver, waits
for StreetZim's health check, then starts OpenStreetMap with
`GPS_UPSTREAM=http://10.88.0.216:8093` and no USB device access. If StreetZim is
disabled (`street_zim_enabled=false`), not installed, or fails startup, it is
stopped and OpenStreetMap retains its local GPS reader. A GPS fix is not required
for StreetZim startup. Stopping OpenStreetMap does not stop the shared GPS.
Stopping StreetZim after a successful boot makes GPS unavailable in both viewers
until StreetZim restarts; there is no automatic second serial reader.

## USB GPS

### Share the existing Maps receiver (optional standalone setup)

The existing Maps container owns the serial port. StreetZim relays its
`/api/gps` response through the reader's own origin. Nothing needs changing in
Maps. Both viewers can use the same receiver without competing for NMEA bytes.
Use `-e GPS_MODE=relay -e GPS_UPSTREAM=http://10.88.0.212:8080` and omit
`--privileged -v /dev:/dev` when creating StreetZim in this mode. Do not use it
when OpenStreetMap itself relays back to StreetZim. No USB devices or privileged
access are given to StreetZim in this mode.
If Maps is stopped or has no receiver/fix, browsing and manual route selection
still work, and GPS status explains the missing location.

### Read the dongle directly

Use this when no other service is reading that receiver. Running two serial
readers on the same dongle can lose NMEA data. This mode is self-contained:
copies of the Library NMEA reader are included under `gps/`.

```bash
ls -l /dev/serial/by-id/
sudo python3 manage.py start --gps-device /dev/serial/by-id/YOUR-GPS-RECEIVER
```

The chosen device is mapped to `/dev/streetzim-gps`; default baud is 9600.
Pass `sudo env GPS_BAUD=4800 ...` if the receiver needs another speed.
Only that device is exposed. There is no privileged container or `/dev` tree
mount. After unplugging/reconnecting it, recreate the container to refresh
the device mapping if Linux changed the node. The serial reader itself retries
temporary read failures and checks NMEA checksums.

Compose equivalent:

```bash
sudo env GPS_DEVICE=/dev/serial/by-id/YOUR-GPS-RECEIVER \
  podman compose -f compose.yaml -f compose.gps.yaml up -d --build
```

## How the adapter works

Kiwix serves archives privately on loopback port 8094 under `/maps/`. nginx
exposes 8093 and inserts a local GPS script before each HTML page's scripts.
Catalog links open the map directly instead of nesting it in Kiwix's viewer.
The archive stays read-only and is not repacked. Binary tiles, routing data,
search indexes and worker scripts pass through nginx without substitution.

The injected script provides the browser geolocation methods used by MapLibre
and StreetZim's navigation HUD, polling the local `/api/gps` endpoint. It also
adapts MapLibre's geolocation permission check so this appliance feed works
over the Library's HTTP hotspot. It never requests the phone's location.
All clients follow the Library device, not their own positions. A status badge
links back to the GPS diagnostics page.

Only connected, confirmed GPS receivers with a valid fix at most 10 seconds
old can update location. A stale/disconnected fix produces a location error,
not another live position. A previous marker may remain visible in upstream
StreetZim while its status badge reports loss of fix. Altitude is passed through;
speed and heading are unknown, so StreetZim uses its route-direction fallback.
The accuracy circle uses a conservative 100 m display estimate: the existing
NMEA API does not report measured horizontal accuracy. This is not a precision
claim. No position history is written to disk.

The bridge targets the StreetZim viewer reviewed at upstream commit
`5e9283cea716cd21fd9fae994ecf907460c9b5c7`. Future archives with different page
markup, restrictive content policies or location interfaces may need updates.
There is no bundled StreetZim map, GraphHopper or upstream archive builder.
Download maps through the separate Downloads service. Search/routing run in the client's browser using the
archive's own data; verify performance on the intended phone/tablet.

## Check and troubleshoot

```bash
sudo podman logs street_zim
curl -f http://localhost:8093/health
curl http://localhost:8093/api/status
curl http://localhost:8093/api/gps
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/test_gps_adapter.cjs
```

Optional browser integration test (Playwright installed separately):

```bash
node tests/browser_smoke.cjs
```

It requires a running reader with a StreetZim map. Set `STREET_ZIM_URL` to test
another host, and `STREET_ZIM_BROWSER` for an existing Chromium executable.
It blocks external requests and checks actual map tiles, the MapLibre location
button with a synthetic fix, stale-fix rejection, recovery, and the mobile home
page. These simulated locations do not verify physical receiver reception.

Initial validation used the published Washington, DC archive dated 2026-10-24
(about 110 MB). That sample remains in the development checkout's optional
`zims/` test folder; it is not in the shared archive folder. Maps are not bundled
in Git or the image. The shared folder must contain a StreetZim archive to use
its map/GPS features. The local test folder is excluded from Git and the image
build context.

To check the optional serial mode in a disposable container without attaching
hardware (from this folder):

```bash
sudo podman run --rm -e GPS_MODE=serial --entrypoint python3 \
  -v "$PWD/tests:/checks:ro,z" localhost/street_zim:latest /checks/direct_gps_smoke.py
```

`/health` checks the reader process and catalog, independently of GPS reception
or map count. `/api/status` lists loaded filenames and the GPS source. A missing
GPS upstream returns HTTP 503 with `fix_valid: false`; it does not prevent maps
from loading. Kiwix/nginx or direct-GPS process exits stop the container so its
restart policy can recover. Internet is only needed for the initial build and
map acquisition.

For relay mode, test `http://10.88.0.212:8080/api/gps` from the appliance. If Maps
uses another address, set `GPS_UPSTREAM` when creating StreetZim. For direct mode,
check the receiver path, baud and permissions. Do not select the Meshtastic
radio's serial port.

The copied GPS modules retain the repository's BSD license in `gps/LICENSE`.
They are intentionally independent copies; later changes in `library_maps`
are not automatically incorporated here. GPS parsing and state tests copied
from Maps run alongside the reader's own tests.
