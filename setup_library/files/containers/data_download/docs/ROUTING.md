# Routing data sources

The **Routing** tab downloads US regional OSM extracts from Geofabrik. After a
file completes, press **Use after restart** in the routing panel, then shut down
and restart the Library. Startup activates the selection and builds directions.
The page also lets you cancel a pending choice. Previously downloaded regions
remain on USB so you can switch back later without downloading them again.

This requires the updated downloader image, updated `/root/start_library.yml`,
and installed `localhost/library_maps-graphhopper:11` image. The web container
queues a request; it does not control Podman or restart services itself. A
standalone downloader without the Library boot playbook only downloads and
records choices; use manual GraphHopper setup in that case.

## Where to download

[Geofabrik's download server](https://download.geofabrik.de/) provides free
regional OpenStreetMap extracts, normally updated daily. Choose **`.osm.pbf`**
for the Library's GraphHopper routing engine.

| Area | Download location |
| --- | --- |
| Worldwide regional directory | [Choose a continent and region](https://download.geofabrik.de/) |
| US states | [United States subregions](https://download.geofabrik.de/north-america/us.html) |
| Georgia, USA | [Georgia overview and current files](https://download.geofabrik.de/north-america/us/georgia.html) |
| Georgia PBF | [georgia-latest.osm.pbf](https://download.geofabrik.de/north-america/us/georgia-latest.osm.pbf) |

These are OSM source extracts, not prebuilt GraphHopper graph caches. The Library
builds its graph locally using its installed GraphHopper version and car profile.
The shapefile, GeoPackage, and PMTiles alternatives are not the routing input
expected by the current configuration.

## How the Library uses the data

The current [GraphHopper configuration](../../library_maps/graphhopper/config.yml)
uses one active extract:

| Purpose | Appliance path |
| --- | --- |
| Optional named downloads | `/Library/maps/osm/georgia-latest.osm.pbf`, etc. |
| Verification receipts | `/Library/maps/osm/<region>-latest.osm.pbf.json` |
| Pending selection | `/Library/maps/osm/routing-pending.json` |
| Last activated selection | `/Library/maps/osm/routing-active.json` |
| Active routing extract | `/Library/maps/osm/region.osm.pbf` |
| Graph built by GraphHopper | `/Library/maps/graph-cache/` |
| Display tiles, managed separately | `/Library/maps/pmtiles/` |

The active extract is mounted as `/data/osm/region.osm.pbf` in GraphHopper. Routes
are limited to its coverage; choosing a different PMTiles layer in the viewer
does not switch the routing region. Several separate PBF downloads do not
automatically become a combined routing graph.

For manual setup, the existing [get-osm.sh](../../library_maps/scripts/get-osm.sh)
helper already downloads a US state's extract from Geofabrik or accepts a local
PBF. See the [viewer and routing setup](../../library_maps/README.md#b-viewer--routing-compose).
On the appliance, the [startup playbook](../../../start_library.yml) looks for
`region.osm.pbf` and starts the installed GraphHopper image when it is present.
It rebuilds the cache if the active extract is newer than the completed graph.
Standalone Compose uses its own `GRAPH_CACHE_DIR` setting, so check that path
before resetting a cache.

Stop the routing service before replacing its active data or clearing its cache.
Finish and validate a new download before activating it; leave the previous
working extract available until the replacement is ready. A first import or
region change needs time to build the graph before directions are available.

Start with a small regional extract on a Raspberry Pi. Importing OSM data takes
more RAM and storage than the download size alone suggests; a whole-country
extract or even a large state may exceed a small Pi's available memory. Allow
space for the PBF and generated graph, and check the GraphHopper logs during import.

## Credit and licensing

Thank you to **Geofabrik** for preparing and hosting regional extracts and to
**OpenStreetMap contributors** for the underlying mapping work. Geofabrik's
[download page](https://download.geofabrik.de/) identifies the data as ODbL 1.0;
retain the applicable license notices and OpenStreetMap attribution. Download
availability, file sizes, and URLs can change.

## Verification and activation

Each routing download is checked against the exact upstream size, OSM PBF header,
and Geofabrik MD5 sidecar. A SHA-256 receipt is stored for startup verification.
These checks detect transfer mismatches; the header check is not full semantic
validation of OSM data. If Geofabrik updates a file during a transfer, refresh
the sources before retrying after a size or checksum error.

Selecting a region reserves room for a second copy. At boot, the helper checks
space again, copies to a temporary file, and verifies SHA-256 before replacing
`region.osm.pbf`. The named download stays in place; an old active extract is only
replaced after the new copy verifies. Startup invalidates the completed graph
marker so the appliance rebuilds its derived cache before serving new directions.

If activation fails, the pending request remains for retry, and the helper records
an error for the Routing panel. Failed copies or checks leave the previous active
extract intact. Boot image/Podman errors appear in `journalctl -u start_library.service`.
Cancel or change a pending selection from the UI if you want to keep using the
previous region. The displayed last-activated region is a selection record, not
an engine readiness check; wait for the routing import before requesting directions.

Only US regional downloads are cataloged in the UI for now. The worldwide links
above remain useful for manual setup. There is no automatic merge of regions or
automatic routing-region switch when selecting a different displayed PMTiles map.
