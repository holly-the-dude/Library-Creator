# library_maps

A lightweight PMTiles map tile server for Raspberry Pi, based on `rasbase_master` (Debian 13, arm64).

Serves `.pmtiles` files via nginx with HTTP range request support. Includes a built-in MapLibre GL JS viewer with a state selector, in-tile place/street search, a map-layer on/off panel, and optional car routing (turn-by-turn directions) via a bundled GraphHopper service. It is fully offline: no geocoder/Photon and no internet/CDN access are required at runtime.

## Appearance and phone controls

The controls share Data Download's dark purple panels, green action buttons, and
gold (`#f3b41e`) selected buttons. The basemap keeps its existing colors.

Use **Hide controls** in the top-right corner to hide the map selector, search,
GPS, directions, layers, zoom buttons, and popup labels. **Show controls** stays
available to bring them back. GPS tracking, route lines, markers, and entered
values are preserved; map attribution remains visible. You can still pan and
pinch to zoom while the controls are hidden.

On phones (screens up to 700px wide), controls start hidden. When shown, panels
form one scrollable column. Wider screens start with the controls visible. Your
choice is remembered in the browser when local storage is available.

Rebuild the `library_maps` image and recreate its container to install the skin
and toggle. The files are bundled locally; no internet is needed to use them.
Controller checks: `node --test test_gps_control.js test_map_ui.js`.

## Automatic font and sprite setup

The image bundles the working Library map fonts and version 4 light sprites.
Before starting nginx, `ensure_map_assets.py` checks the mounted
`/storage/maps/basemaps-assets/` and copies each missing file from the seed at
`/opt/library_maps/basemaps-assets/`. With the normal bind mount, this populates
`/Library/maps/basemaps-assets/` on the USB drive automatically.

The build verifies the bundled files against `basemaps-assets/SHA256SUMS`.
No asset download is needed at startup. Existing files and custom additions
are preserved, and partially populated folders are repaired file by file.
Copies use temporary files and rename so interrupted writes can be retried on
the next start. Logs report how many files were copied and preserved.

Mount `/Library/maps` **read-write** when assets need installation; Compose now
does this by default. A fully populated read-only mount still works, but a
missing file on a read-only/full/unwritable drive stops startup with an explicit
error. Existing empty/corrupt files are not automatically replaced. The helper
also refuses symlink destinations and file/directory conflicts.

The seed contains Noto Sans Regular/Medium/Italic glyph ranges from the working
USB, the 1x/2x light sprites, and upstream license notices. It is not a complete
worldwide font pack; additional glyph ranges can be installed beside it. See
[asset provenance and licenses](basemaps-assets/README.md). PMTiles and routing
data remain on the USB and are not bundled into the image.

After updating an existing installation, **rebuild and recreate** the maps
container to use the new entrypoint and seed. Restarting an old image alone will
not add this feature. New containers check on every start, including offline boots.

Helper regression checks (no network or USB required):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_map_assets.py' -v
```

## Two ways to run

### A) Viewer only (no routing)

```bash
podman build -t library_maps .
podman run -d --name library_maps --add-host graphhopper:10.88.0.213 \
  -p 8080:8080 -v /Library/maps:/storage/maps localhost/library_maps:latest
```

### B) Viewer + routing (compose)

Routing adds a second container (GraphHopper) that imports an OSM extract and answers `/api/route`.

Get regional `.osm.pbf` extracts from [Geofabrik](https://download.geofabrik.de/),
including its [US state downloads](https://download.geofabrik.de/north-america/us.html).
See the [routing-data reference](../data_download/docs/ROUTING.md) for Georgia,
the active `region.osm.pbf` path, import requirements, and source credits.
The Data Download web UI now offers US routing extracts. Download a region,
choose **Use after restart**, then shut down and restart the Library. This needs
the updated startup playbook and the GraphHopper image; standalone Compose
continues to use the manual steps below.

```bash
cp .env.example .env                       # adjust MAPS_DIR / OSM_DIR if needed
./scripts/get-osm.sh colorado              # or: ./scripts/get-osm.sh /path/to/extract.osm.pbf
podman compose up -d
podman compose logs -f graphhopper         # watch the first import
```

Then open `http://<host-ip>:8080/`. Use the **Directions** panel (bottom-left): set Start/Destination by typing `lat,lon`, by clicking **Map** then clicking a point, then press **Route**. The route line and turn-by-turn list are computed locally by GraphHopper — no internet or geocoder.

Routed points must lie inside the OSM extract you imported (e.g. a Colorado graph cannot route to Georgia). Replace the extract with `./scripts/get-osm.sh <region>` then `./scripts/reset-routing-cache.sh && podman compose up -d`.

## Map layers on/off

The **Layers** panel (bottom-right) groups the current style's layers into categories (Labels, Roads, Water, Buildings, Land, Boundaries, Points of interest) and toggles each group's visibility. The panel rebuilds automatically when you switch maps in the state selector.

## USB / serial GPS

Plug an NMEA USB GPS (such as a VK-172 or u-blox receiver) into the **Library device**.
The GPS location belongs to the Library, and is shared with all connected map clients.
No browser location permission, HTTPS, or internet connection is needed.

- **Use GPS** appears when a serial candidate is detected. A fresh fix updates
  the map position automatically; the button recenters the map and resumes following.
  Panning or entering manual coordinates lets you explore elsewhere.
- A **green pin** means a fresh GPS fix. A **red pin** means manual coordinates or
  the last known GPS position after the fix is lost. Coordinates older than 10 seconds
  are no longer treated as a live fix. Text labels also describe the pin status.
- **GPS status** opens live diagnostics even when no receiver is connected: serial
  device, baud rate, fix/connection status, latitude and longitude, fix age, satellites
  used, satellites in view by NMEA talker, HDOP, altitude, and the last valid sentence.
  In-view counts are kept separate because combined GNSS reports can overlap with
  individual constellations. Missing counts mean the receiver has not reported them.

The Library's `start_library.yml` already starts maps with USB discovery and hotplug
access. It uses the existing privileged container plus a host `/dev` bind mount so
devices plugged in after startup become visible. This is for a **rootful Linux
appliance**; do not add `:z` or `:Z` to the `/dev` mount.

For a standalone Linux viewer with GPS:

```bash
sudo podman run -d --name library_maps --replace --privileged \
  --restart unless-stopped --add-host graphhopper:10.88.0.213 \
  -v /dev:/dev -p 8080:8080 -v /Library/maps:/storage/maps \
  localhost/library_maps:latest
```

For compose, opt into the same Linux device access (the base compose file also
works without a GPS):

```bash
sudo podman compose -f compose.yaml -f compose.gps.yaml up -d --build
```

The optional override grants privileged host-device access, matching the appliance
startup configuration. For a fixed receiver without hotplug, a standalone container
can instead use `--device /dev/ttyACM0` without `--privileged` or the `/dev` mount;
the device must exist at container creation and reconnection may require recreation.

Detection prefers a GPS-labelled port, then a single USB serial port. A generic serial
port is only a candidate until checksum-valid GPS sentences arrive. If several ports
are possible, diagnostics list them instead of guessing. The default baud is 9600;
override with `-e GPS_BAUD=4800`, or set it in compose's `.env`.

The runtime playbook defaults `gps_port` to empty (automatic detection). Its
Meshtastic probe skips GPS-labelled devices and the explicitly configured
`gps_port`. A generic radio adapter can still look like a GPS candidate to the
maps reader, so pin the receiver on a Pi with both devices:

```bash
sudo ansible-playbook /root/start_library.yml \
  -e gps_port=/dev/serial/by-id/your-gps-receiver -e gps_baud=9600
```

Use the receiver's real by-id path and save it in the deployed playbook's variables
for subsequent boots; a command-line override affects only that run. Radio adapters
may appear as either `ttyUSB` or `ttyACM`; neither name proves a device is a GPS.

The standalone `rebuild.sh`, `compose.yaml` and `.env.example` instead default to a
specific u-blox receiver's by-id path. Override `GPS_PORT` for your receiver. The
Compose expression uses a fallback for both unset and empty values, so an empty
`.env` value does **not** enable automatic detection without editing that expression.
Stop other serial readers before testing the same device directly.

Give the receiver a clear view of the sky. GGA or RMC output is required for location;
GGA reports satellites used and GSV reports satellites in view. Binary-only receivers
need NMEA enabled. Wrong baud, permission errors, ambiguous ports, stale fixes, and
disconnections appear in **GPS status**. The reader retries automatically. The selected
map still needs tiles for the GPS location; GPS cannot supply missing map coverage.

`gps_service.py` reuses the checksum/coordinate parsing in `read_gps.py`, holds one
serial connection for all clients, and keeps status in memory. nginx proxies
`/api/gps` to its loopback listener (`127.0.0.1:8765`) with caching disabled. The
browser polls every two seconds. `read_gps.py` still works as a standalone diagnostic:

```bash
python3 read_gps.py --list-ports
python3 read_gps.py --port /dev/ttyACM0 --baud 9600 --once
```

Stop the maps container before reading the same port from the host with that CLI.
Use `curl http://127.0.0.1:8080/api/gps` to inspect the running service without opening
another serial connection.

After source changes, rebuild `localhost/library_maps:latest` and recreate the maps
container. For offline distribution, regenerate `library_maps.tar` with the project's
`create_tar_pods.sh`; editing the sources does not update an existing saved image.

GPS regression checks (Python standard library and Node.js; no receiver required):

```bash
python3 -m unittest discover -s tests -v
node test_gps_control.js
```

## Volume Layout

Mount a directory to `/storage/maps` with this structure:

```
/storage/maps/
├── pmtiles/                    # .pmtiles map files (required)
│   ├── alabama_2025-12.pmtiles
│   ├── oregon_2025-12.pmtiles
│   └── ...
├── basemaps-assets/            # Required fonts/sprites for Protomaps state maps
│   ├── fonts/
│   └── sprites/
└── styles/                     # Map style JSON files (optional)
```

## Container Management

```bash
podman stop library_maps
podman start library_maps
podman rm library_maps
podman logs -f library_maps
```

## Endpoints

| Path | Description |
|------|-------------|
| `http://<ip>:8080/` | Built-in map viewer |
| `http://<ip>:8080/health` | Health check |
| `http://<ip>:8080/pmtiles/<file>.pmtiles` | PMTiles files (range requests supported) |
| `http://<ip>:8080/basemaps-assets/` | Fonts and sprites |
| `http://<ip>:8080/styles/` | Style JSON files |
| `http://<ip>:8080/api/route` | Car routing (proxied to GraphHopper; only when running the compose stack) |
| `http://<ip>:8080/api/gps` | Live serial GPS status and last accepted position (JSON, no cache) |

## Downloading State Maps

### Map appears in the dropdown but the display is blank

The dropdown only confirms that a `.pmtiles` file exists. Protomaps state maps
also need the fonts and sprites at these host paths:

```text
/Library/maps/basemaps-assets/fonts/Noto Sans Regular/0-255.pbf
/Library/maps/basemaps-assets/sprites/v4/light.json
/Library/maps/basemaps-assets/sprites/v4/light.png
```

Keep all supplied font ranges, font families, and the `light@2x` sprite files,
not just these examples. Folders at `/Library/maps/fonts` and
`/Library/maps/sprites` are one level too high for the viewer's URLs. If an asset
archive was unpacked there, copy the existing folders into the expected location
on the Pi (without replacing files already present):

```sh
sudo mkdir -p /Library/maps/basemaps-assets
sudo cp -an /Library/maps/fonts /Library/maps/sprites /Library/maps/basemaps-assets/
curl -fI http://127.0.0.1:8080/basemaps-assets/sprites/v4/light.json
curl -fI http://127.0.0.1:8080/basemaps-assets/fonts/Noto%20Sans%20Regular/0-255.pbf
```

New images automatically populate these paths on startup. The manual copy above
is useful for older images or existing customized assets. Both requests should
return HTTP 200. Reload the browser page after correcting
the folders; these mounted asset changes do not require a container rebuild or
restart. Use a hard refresh if the browser retained failed asset requests.
Natural Earth's roads-only map does not use these assets, so it can work while
Protomaps state maps fail. To check a downloaded archive separately:

```sh
sudo podman exec library_maps pmtiles verify /storage/maps/pmtiles/georgia_2025-12.pmtiles
```

### State download script

The `download_states.sh` script downloads pre-built PMTiles from [project-nomad-maps](https://github.com/Crosstalk-Solutions/project-nomad-maps). All 50 US states are available:

| Region | States |
|--------|--------|
| Pacific | Alaska, California, Hawaii, Oregon, Washington |
| Mountain | Arizona, Colorado, Idaho, Montana, Nevada, New Mexico, Utah, Wyoming |
| West South Central | Arkansas, Louisiana, Oklahoma, Texas |
| East South Central | Alabama, Kentucky, Mississippi, Tennessee |
| South Atlantic | Delaware, Florida, Georgia, Maryland, North Carolina, South Carolina, Virginia, West Virginia |
| West North Central | Iowa, Kansas, Minnesota, Missouri, Nebraska, North Dakota, South Dakota |
| East North Central | Illinois, Indiana, Michigan, Ohio, Wisconsin |
| Mid-Atlantic | New Jersey, New York, Pennsylvania |
| New England | Connecticut, Maine, Massachusetts, New Hampshire, Rhode Island, Vermont |

The script skips files that are already downloaded, so it's safe to re-run.

## Extracting Custom Regions

The container includes the `pmtiles` CLI. You can extract regions from any PMTiles source:

```bash
# Extract using a GeoJSON boundary
podman exec library_maps pmtiles extract \
  https://build.protomaps.com/YYYYMMDD.pmtiles \
  /storage/maps/pmtiles/my_region.pmtiles \
  --region=/storage/maps/my_region.geojson \
  --maxzoom=15

# Extract by bounding box
podman exec library_maps pmtiles extract \
  https://build.protomaps.com/YYYYMMDD.pmtiles \
  /storage/maps/pmtiles/region.pmtiles \
  --bbox=-105.5,-104.5,39.5,40.5 \
  --maxzoom=14
```

## Building from OSM Data

The `build_state_pmtiles.sh` script can generate PMTiles from Geofabrik OSM extracts using Planetiler (requires Java 21+):

```bash
./build_state_pmtiles.sh --states=colorado --output-dir=../maps/pmtiles
```

## Container Details

- **Base image**: `localhost/rasbase_master:latest` (Debian 13 trixie, arm64)
- **Web server**: nginx on port 8080
- **GPS reader**: Python + pySerial, loopback status API on port 8765
- **PMTiles CLI**: go-pmtiles 1.30.2 at `/usr/local/bin/pmtiles`
- **Map viewer**: Built-in MapLibre GL JS + protomaps basemaps (baked into image)
- **Map storage**: `/storage/maps/` (mount your volume here)

## Notes

- The viewer is fully offline: MapLibre GL JS, PMTiles JS, and the Protomaps basemaps JS are vendored into the image at `/var/www/html/vendor/`, and map fonts (glyphs) + sprites are served from `/storage/maps/basemaps-assets/`. No internet or CDN access is needed by clients. This matters because clients on the offline hotspot network cannot reach the public internet.
- Startup fills missing `sprites/v4/light.*` and bundled `fonts/Noto Sans {Regular,Medium,Italic}/*.pbf` files under `/storage/maps/basemaps-assets/` from the image. Additional font ranges can be installed from the upstream Protomaps assets as needed.
- The `.pmtiles` tile data itself is served entirely offline from the local volume
- Files use the naming convention `statename_2025-12.pmtiles`
- On systems where `curl` prefers IPv6, use `127.0.0.1` instead of `localhost` to access the container

## Shared build workflow

The parent [`build_pods.sh`](../build_pods.sh) builds the maps image and its nested
GraphHopper image alongside the other services, including Meshtastic and meshflash.
Use rootful Podman consistently for appliance builds and startup. See the
[developer guide](../../../../docs/DEVELOPERS.md#container-build-pipeline) for exports;
the top-level tar-export loop does not include the nested GraphHopper image.
