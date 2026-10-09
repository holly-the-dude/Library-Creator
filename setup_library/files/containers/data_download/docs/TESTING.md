# Data Download testing guide

The suite in [tests/test_downloader.py](../tests/test_downloader.py) verifies
the Python downloader without external network traffic or writes to the real
`/Library` drive. See [DEVELOPMENT.md](DEVELOPMENT.md) for program structure and
[API.md](API.md) for endpoint behavior.

## Run automated checks

From `setup_library/files/containers/data_download`:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
node --check static/app.js
```

Python tests need only the standard library. Node is optional for the JavaScript
syntax check; it is not an application runtime dependency. HTTP tests require
permission to bind ephemeral loopback ports. If an execution sandbox blocks
sockets, run the suite where localhost sockets are allowed. A socket-permission
failure does not by itself indicate a downloader regression.

To run the suite inside the image, mount the tests and override its entrypoint:

```sh
sudo podman build -t localhost/data_download:latest -f Containerfile .
sudo podman run --rm --network=none \
  --mount "type=bind,src=$PWD/tests,dst=/tests,ro" \
  --mount "type=bind,src=$PWD/../../library_control.py,dst=/library_control.py,ro" \
  --entrypoint python3 localhost/data_download:latest \
  -m unittest discover -s /tests -v
```

The tests are excluded from the build context by `.containerignore`, so the
read-only mount is required. The image working directory makes `app` and
`sources` importable. Use the same Podman image store for build and test.

## Coverage

| Test class | Covered behavior |
| --- | --- |
| `DiscoveryTests` | Connectivity fallback, all-host failure, HTTP rate limits, captive-portal redirects, exact ZIM sizes, category filtering, malformed ZIP anchors, LFS metadata, unsafe filenames |
| `StorageTests` | Mount/root checks, symlinks/traversal, free-space reserve, successful transfers, Range/If-Range resume, ignored/invalid ranges, complete ZIP reuse, truncated transfers, checksum/format rejection, cancellation |
| `StorageTests` | PDF-only extraction, unsafe ZIP entries, expanded-space checks, preservation of existing categories, CRC failure cleanup, source isolation/cache reload, duplicate queue submissions, publication of all four content types |
| `StorageTests` | Offline drive reporting with discovery gated on connectivity, exact offline text, reconnection refresh, 30-second timing, and manual refresh gating |
| `HTTPTests` | Static/API GET routes and headers, continued responses with a broken access-log pipe, token enforcement, and rejection of download requests outside the accepted workflow |
| `RestartTests` | Real Unix socket requests with systemctl mocked, rejection of arbitrary commands, active-job blocking, duplicate suppression, failed-host retries, and missing-handler fallback |
| `UploadTests`, `UploadHTTPTests` | All three destinations, folder/Unicode paths, empty files, offline uploads, ZIP cleanup and CRC validation, conflict preservation, unsafe paths/symlinks, publication rollback, space limits, restart exclusion, token enforcement, and streaming above the JSON size limit |

Restart tests never invoke a real shutdown or systemd action. The extra host
Python module mount above is needed only for these bridge tests. Before a manual
restart test on a Pi, finish downloads, select a routing region if needed, and
expect the Library Wi-Fi connection to drop. Check that both splash screens
appear, power remains connected, and services return after reboot. This manual
test really reboots the appliance; it is separate from the automated suite.

`Response` is an in-memory `BytesIO` object with HTTP status and headers. Source
requests are patched to return these fixtures or errors. ZIP tests create small
temporary archives, including deliberate corrupt/unsafe entries. `TemporaryDirectory`
cleans test storage, and server cleanup closes each loopback listener.

Connectivity timing tests use mocked monotonic time and event waits; they do not
sleep for real 30-second intervals. The worker integration test consumes exactly
its fixture batch without leaving a download thread running afterward. HTTP
tests create an application without starting discovery.

## Local development

To run the actual application against disposable storage:

```sh
mkdir -p /tmp/library-download-test
LIBRARY_ROOT=/tmp/library-download-test REQUIRE_MOUNT=0 python3 app.py
```

Open `http://127.0.0.1:4286`. Unlike the automated tests, this starts real source
discovery when online; selecting content initiates real downloads. It binds to
all interfaces, as the container does. Use `REQUIRE_MOUNT=0` only for a deliberate
test directory. Ctrl-C stops the application.

## Raspberry Pi acceptance checks

Perform these with a test drive and a network connection you can disconnect
without losing the local browser/SSH connection to the Pi. Build/run instructions
and the host mount guard are in the [README](../README.md#build-and-run-on-the-raspberry-pi).

1. **Offline startup:** start without external internet access. The local page
   should remain reachable and display the exact offline message. New downloads
   and source refresh should be disabled; discovery should wait for connectivity.
   Drive capacity and local uploads should work without internet.
2. **Recovery:** restore the Pi's internet access. A subsequent 30-second check
   should clear the message and start discovery without a page reload or container
   restart. The browser's own 2.5-second polling adds a small display delay.
3. **Storage:** compare UI capacity with `df -B1 /Library`. Confirm it is the USB
   filesystem and the default reserve is 256 MiB. Check behavior with a deliberate
   read-only test mount; do not remove a mounted drive during a write.
4. **Catalogs:** verify each source reports its own status, source searches work,
   Wikipedia's latest-edition filter works, and Survivor lists ZIP categories
   rather than individual PDF downloads.
5. **Downloads:** select a small map/ZIM/category that fits. Check progress and
   final destinations. Confirm non-PDF ZIP members are absent from the published
   category, and existing content is refused. Avoid filling a real drive just to
   test low-space behavior; use the automated tests or a disposable limited filesystem.
6. **Retry:** cancel a transfer and retry it. When the source supports validators
   and ranges, verify resume behavior; otherwise a clean restart is expected.
   Restarting the container clears job history, but selecting the same item again
   can reuse a partial file. No job should restart automatically.
7. **Readers:** refresh Maps, register downloaded ZIMs with Kiwix, and regenerate
   the PDF index as described in the [reader instructions](../README.md#making-downloaded-content-visible).
8. **Shutdown:** stop the container with Podman and confirm it exits cleanly.
   Inspect `.data_download` for interrupted work before reclaiming temporary files.
9. **Uploads:** select Upload files in the same row as the download categories.
   Try a single file, multiple files, and a folder for each destination. Verify
   progress, preserved folder paths, the light-blue capacity panel, and offline
   operation. Upload a ZIP with mixed file types; verify extraction and archive
   removal. Existing files must be kept when a conflicting upload fails. Try
   narrow/mobile layouts and keyboard navigation as well as desktop browsing.
   Selected tabs and upload categories should have a `#f3b41e` background;
   checked file rows should have a purple fill and gold left-edge marker.
10. **Upload reminders:** after music uploads, confirm the popup gives the
    **Gear icon → Scanner → Scan Now → Albums → refresh** instructions. After
    data or ebook uploads, confirm the restart dialog offers **Restart Library**
    and **I'll restart later**, waiting for active transfers to finish. Closing
    a reminder should not cause it to reopen on the next poll. A batch with no
    successful uploads should not trigger a reminder; a partially successful
    batch should show one for saved files. Music and restart dialogs must not
    appear on top of each other.

## Validation limits

Automated fixtures verify control flow and file handling, not current remote
website layouts or every archive format. Live discovery was separately checked
against all three sources during implementation. Recheck live metadata when
changing parsers; full multi-gigabyte downloads are not needed for listing tests.

The automated suite does not prove browser rendering, mobile layout, USB unplug
behavior, all USB filesystem semantics, power-loss recovery, or compatibility
with every Pi image. The ARM64 image has been built and tested; use the manual
checks on the target Pi and drive before relying on a deployment.

## Routing checks

`tests/test_routing.py` covers safe catalog links, exact metadata, PBF signatures,
MD5/SHA-256 failures, interrupted hashing, persistent/cancellable selection,
space failures, atomic activation, cache invalidation, and symlink/path rejection.
HTTP tests cover the selection token and invalid-file responses; the download
worker test publishes all four content types and a verified routing receipt.

For a Pi acceptance test, install the updated downloader image and startup
playbook plus GraphHopper. Download a small region, select **Use after restart**,
and verify existing directions are unchanged before shutdown. Restart and watch
GraphHopper import; confirm routes inside the chosen region. The active file is
`/Library/maps/osm/region.osm.pbf`; the named download remains available to select
again. Selecting another region replaces the active region on a later startup.

The boot handoff has separate Ansible integration tests using fake Podman commands:

```sh
# From the repository root; requires Ansible and PyYAML.
python3 -m unittest discover -s setup_library/tests -p test_routing_startup.py -v
```

These cover no pending request, stop-before-activation ordering, missing images,
and activation failure recovery. Live Geofabrik discovery has also been checked
against the US overview and Georgia's HEAD/MD5 metadata without fetching its PBF.
