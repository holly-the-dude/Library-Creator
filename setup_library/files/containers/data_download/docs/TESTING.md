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
| `StorageTests` | PDF-only extraction, unsafe ZIP entries, expanded-space checks, preservation of existing categories, CRC failure cleanup, source isolation/cache reload, duplicate queue submissions, publication of all three content types |
| `StorageTests` | Offline startup before storage/discovery, exact offline text, reconnection refresh, 30-second timing, and manual refresh gating |
| `HTTPTests` | Static/API GET routes and headers, continued responses with a broken access-log pipe, token enforcement, and rejection of download requests outside the accepted workflow |

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
   and source refresh should be disabled; storage initialization and discovery
   should wait for connectivity.
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

## Validation limits

Automated fixtures verify control flow and file handling, not current remote
website layouts or every archive format. Live discovery was separately checked
against all three sources during implementation. Recheck live metadata when
changing parsers; full multi-gigabyte downloads are not needed for listing tests.

The automated suite does not prove browser rendering, mobile layout, USB unplug
behavior, all USB filesystem semantics, power-loss recovery, or compatibility
with every Pi image. The ARM64 image has been built and tested; use the manual
checks on the target Pi and drive before relying on a deployment.
