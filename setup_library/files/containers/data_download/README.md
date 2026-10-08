# Library Data Download

A small Python web application for Raspberry Pi / Podman. Open
**http://library:4826** or **http://<pi-ip>:4826** to choose content for the
mounted Library USB drive. The Library homepage has a **Downloads** tab after
Meshtastic and before Shutdown, linking to **http://10.1.1.1:4826**. Podman
forwards host port **4826** to the app listening on **0.0.0.0:4286** inside the
container. The interface uses
the Library website's dark purple, green, and blue palette, with local assets
and no frontend dependencies.

## Documentation

- [Development guide](docs/DEVELOPMENT.md): Python programs, startup/connectivity,
  threads, discovery, storage, downloads, extraction, and persistent files.
- [HTTP API reference](docs/API.md): endpoints, state/catalog/job fields, request
  tokens, action bodies, and errors.
- [Testing guide](docs/TESTING.md): test coverage, local/container commands, and
  Raspberry Pi acceptance checks.

The Python modules also include function and class docstrings for IDE help.

## Startup and sources

On startup it first checks the Pi's internet connection. While offline, the
main page displays **"No Internet, its really hard to go on like this"** and
the container retries every **30 seconds**. Once connected, it automatically
checks `/Library` filesystem capacity and free space and discovers all three
sources independently in the background. It downloads content only when you
select files and press **Download selected**.

Connectivity checks use small HTTPS HEAD requests to the source sites, falling
back to another host if one is unreachable. Checks continue every 30 seconds
while running, so the message reappears if connectivity is lost and the catalog
refreshes automatically on reconnection. Download/refresh controls are disabled
while offline; the local webpage remains accessible.

| Source | Files offered | Destination on the USB drive |
| --- | --- | --- |
| [Project N.O.M.A.D. Maps](https://github.com/Pendia/Project-N.O.M.A.D-Maps) | Regional `.pmtiles` files, resolving Git LFS pointers | `/Library/maps/pmtiles/<filename>.pmtiles` |
| [Wikipedia ZIM directory](https://dumps.wikimedia.org/kiwix/zim/wikipedia/) | `.zim` files; search by language and filter latest editions | `/Library/wiki/<filename>.zim` |
| [Survivor Library](https://www.survivorlibrary.com/index.php/main-category-index/) | Only category ZIP links, discovered by visiting each section | `/Library/library/<ZIP-name>/<PDF paths from archive>` |

For example, `Accounting.ZIP` extracts its PDFs beneath
`/Library/library/Accounting/`. Other file types inside a ZIP are skipped. The
downloaded ZIP is removed after successful extraction. Existing destination
files or category folders are kept and shown as **Already present**.

## Build and run on the Raspberry Pi

Run from this directory. Use the same rootful Podman image store as the other
Library containers. The default base is `localhost/rasbase_master:latest`.

```sh
sudo podman build -t localhost/data_download:latest -f Containerfile .

# Confirm the USB filesystem is mounted BEFORE creating the container.
mountpoint /Library
findmnt /Library

# This guard refuses to start against an ordinary, unmounted host folder.
mountpoint -q /Library && sudo podman run -d \
  --name data_download --restart unless-stopped \
  -p 0.0.0.0:4826:4286 \
  --mount type=bind,src=/Library,dst=/Library \
  localhost/data_download:latest
```

For a standalone build without `rasbase_master`:

```sh
sudo podman build \
  --build-arg BASE_IMAGE=docker.io/library/debian:trixie-slim \
  -t localhost/data_download:latest -f Containerfile .
```

Python and CA certificates are the only installed packages. There are no
architecture-specific downloads; the base determines ARM64, ARMHF, or AMD64.
Pi hardware testing is still required on your target image and USB filesystem.

Alternatively, with a Podman Compose provider installed:

```sh
mountpoint -q /Library && sudo podman compose up -d --build
```

The container requires `/Library` to be a writable mount point. Inside a
container this confirms the bind mount, so checking that the **host** `/Library`
is the USB mount is also necessary. Mount the USB before container startup and
recreate/restart the container after remounting it. No privileged mode, device
access, or Podman socket is needed. On an SELinux host, shared content may need
the shared `:z` volume label; avoid private `:Z` relabeling of content used by
other containers. Normal Raspberry Pi OS does not use SELinux.

The existing `../build_pods.sh` and `../create_tar_pods.sh` automatically discover
this Containerfile and build/export `data_download.tar`. The Library startup
playbook starts the downloader before the webserver when its image is installed,
after checking the USB mount. Installations without the image skip this service.
The homepage probes the local health endpoint, so **Downloads** remains available
while waiting for internet. Standalone startup and Compose are also supported.

For an existing Pi, load `data_download.tar`, deploy the updated
[`start_library.yml`](../../start_library.yml), and rebuild/recreate the webserver
with its updated configuration. Recreate any older downloader container with
`4826:4286` port publication; restarting a container retains its old port mapping.
The commands above show the standalone mapping. On the next Library startup,
the playbook recreates the named downloader with the correct mapping.

## Using the page

1. Give the **Pi** internet access, then open `http://<pi-ip>:4826`.
2. Check the drive capacity and free space. Each source reports its own status;
   Survivor Library takes longer because every category page must be checked.
3. Pick Maps, Wikipedia, or Survivor Library. Search and select files (up to
   100 per request). Wikipedia initially shows the latest date for each variant;
   uncheck **Latest editions only** to see older snapshots.
4. Press **Download selected**. The queue shows download and extraction progress,
   errors, cancellation, and retry controls. Closing the browser is fine.
5. Use **Refresh sources** to retry unreachable sources or retrieve new listings.
6. After the queue finishes with successful downloads, a popup reminds you to
   **shut down and restart the Library** so the new files become available. Use
   the Library's Shutdown option, wait for shutdown to finish, then start it again.
   The reminder waits until downloads and extraction are idle, and appears once
   per completed batch while the page is open. Its button dismisses the reminder;
   it does not shut down the device.

Downloads run one at a time with 1 MiB streaming buffers. Catalog discovery uses
at most four workers per multi-page source. Files are saved on the Pi's mounted
drive, not the browser's computer. The UI has no login; use it on your trusted
Library LAN, as other clients on that LAN can manage this shared queue.

### Space and integrity

- Capacity comes from the filesystem mounted at `/Library`, not the image layer.
  By default **256 MiB stays free**. Exact known sizes are checked before download;
  free space is checked continuously while writing. Each queued file is checked
  again when its turn starts. Other programs can consume space in the meantime.
- Survivor ZIP sizes are shown as unknown until the server reports a byte count.
  The **Fits available space** filter hides unknown-size archives. Extraction
  checks the ZIP's expanded PDF sizes against the remaining space, while the
  compressed ZIP is still on disk. If space runs out, no final category is published.
- Map downloads check the LFS SHA-256, byte count, and PMTiles header. ZIM downloads
  check the listed byte count and ZIM header (not a full ZIM checksum). PDFs are
  checked against the ZIP CRC while extracting. ZIP paths, symlinks, duplicates,
  and directory traversal are checked before extraction.
- Work files live in `/Library/.data_download/`. Completed files/categories are
  moved into their final location after validation, so consumers do not see
  partially downloaded files or half-extracted categories.
- Interrupted downloads retain their `.part` file. Retry resumes when the server
  supplies an ETag or Last-Modified validator and honors Range/If-Range; otherwise
  it restarts the download. Cancel can take up to the 30-second network timeout.
- The catalog is cached across restarts, loaded after the startup internet check
  succeeds, and retained when individual sources are unavailable.
  The queue/history is held in memory; after restarting the container, select the
  same file again to retry its partial download. Jobs do not resume automatically.
  An abrupt stop during extraction can leave an `extract-*` staging folder; with
  the container stopped, these folders and unneeded `.part`/`.json` pairs may be
  removed from `.data_download/` to reclaim space. Keep `catalog.json` for cached listings.

### Making downloaded content visible

The downloader saves content; existing readers may need their own refresh:

- **Maps:** reload the existing viewer page to rescan its PMTiles directory.
  Current `library_maps` images bundle the standard fonts and sprites and copy
  missing files onto the maps volume at startup; this downloader saves PMTiles
  only. Rebuild/recreate older viewer containers to get
  [automatic asset setup](../library_maps/README.md#automatic-font-and-sprite-setup).
  In particular, fonts and sprites belong inside `/Library/maps/basemaps-assets/`,
  not directly under `/Library/maps/`. A map can appear in the dropdown while
  its required assets return 404. See the
  [blank-map repair instructions](../library_maps/README.md#map-appears-in-the-dropdown-but-the-display-is-blank).
- **Wiki:** register new ZIM files using the existing Wiki workflow, for example
  `sudo podman exec wiki kiwix-manage /wiki/wiki.xml add /wiki/<downloaded-file>.zim`,
  then restart `wiki` to reload its index. See [Wiki README](../wiki/README.md).
- **PDF library:** rerun `sudo podman exec webserver python3 /root/library.py`
  (or restart `webserver`) to detect the changed file count and regenerate its
  indexes. See [Webserver README](../webserver/README.md).

## Configuration and troubleshooting

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `LIBRARY_ROOT` | `/Library` | Root used for storage/capacity checks |
| `PORT` | `4286` | Listening port; if changed, also update publication and healthcheck |
| `REQUIRE_MOUNT` | `1` | Refuse downloads unless storage is a mount point |
| `MIN_FREE_BYTES` | `268435456` | Free-space reserve in bytes |

```sh
sudo podman logs -f data_download
sudo podman port data_download
curl http://127.0.0.1:4826/api/health
```

Health checks confirm the web server is running; drive readiness and source
availability appear in the UI and `/api/state`. DNS/TLS failures, GitHub API
rate limits, source layout changes, and unavailable LFS objects are surfaced as
source/job errors. Correct the Pi clock if HTTPS certificate checks fail.

For a local test directory, outside Podman:

```sh
mkdir -p /tmp/library-download-test
LIBRARY_ROOT=/tmp/library-download-test REQUIRE_MOUNT=0 python3 app.py
```

Use the mount-check override only for deliberate development directories.

## Troubleshooting

### If the container runs but the browser gets an empty reply

On the Pi, check `journalctl -u start_library.service -b` for systemd killing
`conmon` after the startup playbook finishes. The old `Type=simple` unit could
tear down the containers' log monitors when Ansible exited, leaving the
downloader's stderr pipe broken. HTTP access logging then aborted responses.

The corrected [`start_library.service`](../../start_library.service) uses
`Type=oneshot`, `RemainAfterExit=yes`, and `TimeoutStartSec=0`. Install it at
`/etc/systemd/system/start_library.service` and run `sudo systemctl daemon-reload`.
Recreate the downloader from the updated image to restore its log monitor. The
Python handler also tolerates failed access-log writes. Reloading the unit alone
does not repair an already damaged container, and restarting the whole startup
service reruns appliance setup; a full setup rerun is unnecessary for this repair.

Confirm recovery with `curl -f http://10.1.1.1:4826/api/health` and the main page.

## Tests

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
node --check static/app.js
```

Tests use temporary directories, small in-memory responses/ZIPs, and a localhost
HTTP server. They require no external network and do not touch `/Library`.
See the [testing guide](docs/TESTING.md) for details and checks on the target Pi.
