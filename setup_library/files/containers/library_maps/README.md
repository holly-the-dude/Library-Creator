# library_maps

A lightweight PMTiles map tile server for Raspberry Pi, based on `rasbase_master` (Debian 13, arm64).

Serves `.pmtiles` files via nginx with HTTP range request support. Includes a built-in MapLibre GL JS viewer with a state selector, in-tile place/street search, a map-layer on/off panel, and optional car routing (turn-by-turn directions) via a bundled GraphHopper service. It is fully offline: no geocoder/Photon and no internet/CDN access are required at runtime.

## Two ways to run

### A) Viewer only (no routing)

```bash
podman build -t library_maps .
podman run -d --name library_maps --add-host graphhopper:10.88.0.213 \
  -p 8080:8080 -v /Library/maps:/storage/maps localhost/library_maps:latest
```

### B) Viewer + routing (compose)

Routing adds a second container (GraphHopper) that imports an OSM extract and answers `/api/route`.

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
are possible, diagnostics list them instead of guessing. Defaults are auto-detection
and 9600 baud; override with `-e GPS_PORT=/dev/serial/by-id/your-receiver` and
`-e GPS_BAUD=4800`, or set these in compose's `.env`. The playbook accepts
`-e gps_port=/dev/serial/by-id/your-receiver -e gps_baud=4800`.

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
├── basemaps-assets/            # Fonts and sprites (optional, for offline use)
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

- **Base image**: `localhost/rasbase_trixie` (Debian 13 trixie, arm64)
- **Web server**: nginx on port 8080
- **GPS reader**: Python + pySerial, loopback status API on port 8765
- **PMTiles CLI**: go-pmtiles 1.30.2 at `/usr/local/bin/pmtiles`
- **Map viewer**: Built-in MapLibre GL JS + protomaps basemaps (baked into image)
- **Map storage**: `/storage/maps/` (mount your volume here)

## Notes

- The viewer is fully offline: MapLibre GL JS, PMTiles JS, and the Protomaps basemaps JS are vendored into the image at `/var/www/html/vendor/`, and map fonts (glyphs) + sprites are served from `/storage/maps/basemaps-assets/`. No internet or CDN access is needed by clients. This matters because clients on the offline hotspot network cannot reach the public internet.
- If you add new state files or rebuild, ensure `/storage/maps/basemaps-assets/` contains `sprites/v4/light.*` and `fonts/Noto Sans {Regular,Medium,Italic}/*.pbf` (mirror from `https://protomaps.github.io/basemaps-assets/`)
- The `.pmtiles` tile data itself is served entirely offline from the local volume
- Files use the naming convention `statename_2025-12.pmtiles`
- On systems where `curl` prefers IPv6, use `127.0.0.1` instead of `localhost` to access the container
