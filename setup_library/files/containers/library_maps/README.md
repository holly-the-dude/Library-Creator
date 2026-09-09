# library_maps

A lightweight PMTiles map tile server for Raspberry Pi, based on `rasbase_master` (Debian 13, arm64).

Serves `.pmtiles` files via nginx with HTTP range request support. Includes a built-in MapLibre GL JS viewer with a state selector, in-tile place/street search, a map-layer on/off panel, and optional car routing (turn-by-turn directions) via a bundled GraphHopper service. It is fully offline: no geocoder/Photon and no internet/CDN access are required at runtime.

## Two ways to run

### A) Viewer only (no routing)

```bash
podman build -t library_maps .
podman run -d --name library_maps -p 8080:8080 -v /Library/maps:/storage/maps localhost/library_maps:latest
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
- **PMTiles CLI**: go-pmtiles 1.30.2 at `/usr/local/bin/pmtiles`
- **Map viewer**: Built-in MapLibre GL JS + protomaps basemaps (baked into image)
- **Map storage**: `/storage/maps/` (mount your volume here)

## Notes

- The viewer is fully offline: MapLibre GL JS, PMTiles JS, and the Protomaps basemaps JS are vendored into the image at `/var/www/html/vendor/`, and map fonts (glyphs) + sprites are served from `/storage/maps/basemaps-assets/`. No internet or CDN access is needed by clients. This matters because clients on the offline hotspot network cannot reach the public internet.
- If you add new state files or rebuild, ensure `/storage/maps/basemaps-assets/` contains `sprites/v4/light.*` and `fonts/Noto Sans {Regular,Medium,Italic}/*.pbf` (mirror from `https://protomaps.github.io/basemaps-assets/`)
- The `.pmtiles` tile data itself is served entirely offline from the local volume
- Files use the naming convention `statename_2025-12.pmtiles`
- On systems where `curl` prefers IPv6, use `127.0.0.1` instead of `localhost` to access the container
