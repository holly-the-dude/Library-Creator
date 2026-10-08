# Data Download HTTP API

The server listens on `0.0.0.0:4286` by default. Podman publishes it at `http://10.1.1.1:4826`. Its browser UI and API use the
same origin. All routes are implemented in [app.py](../app.py). Requests address
the Pi; downloaded files are written to its mounted Library drive.

## Routes

| Method | Path | Response / action |
| --- | --- | --- |
| GET | `/` | Main HTML page |
| GET | `/app.js` | Bundled frontend JavaScript |
| GET | `/style.css` | Bundled stylesheet |
| GET | `/api/health` | `200` with `{"status": "ok"}` |
| GET | `/api/state` | Storage, internet, source, and job state plus request token |
| GET | `/api/catalog` | State response plus sorted catalog rows and installed flags |
| POST | `/api/refresh` | Request asynchronous discovery if online and no scan is active |
| POST | `/api/download` | Queue selected catalog IDs |
| POST | `/api/cancel` | Set a known job's cancellation event |

Paths are matched exactly; there are no query parameters or trailing-slash
aliases. Unknown GET/POST paths return `404` (POST token validation happens
before routing). Methods outside GET/POST use the base HTTP handler's behavior.

The health endpoint confirms the HTTP service is alive. It does not imply
internet availability, a mounted drive, or successful downloads.

## State response

| Field | Contents |
| --- | --- |
| `internet` | `status` (`checking`, `offline`, `online`) and `message` |
| `storage` | Capacity fields when ready, otherwise a readiness error |
| `sources` | Object keyed by `maps`, `wiki`, and `survivor` |
| `refreshing` | Whether a catalog scan is active |
| `jobs` | List of this process's job records |
| `token` | Per-process request token needed for POST actions |
| `catalog` | Present only on `/api/catalog` |

While offline, `internet.message` is exactly
`No Internet, its really hard to go on like this`. While checking it is
`Checking internet connection…`; online it is an empty string. The backend
checks every 30 seconds, independently of whether any browser is open.

Ready storage contains `ready: true`, `path`, `total`, `used`, `free`, `available`,
and `reserve`. All numeric sizes are bytes; `available` is `max(0, free - reserve)`.
Unavailable storage contains `ready: false`, `path`, and `error`. Before the first
successful internet check, its error is `Waiting for internet connection`.

Source records contain `name`, `url`, `status`, `count`, and `error`. States are
`waiting`, `cached`, `checking`, `available`, `partial`, or `unavailable`.
`checked_at` is a Unix timestamp added after a successful/partial discovery;
it is not updated for a failed attempt. Cached rows may remain after a failure,
and `count` during a scan reflects fresh results, not necessarily all retained
rows. Cached source records do not persist check timestamps across restarts.

Example read-only requests:

```sh
curl http://127.0.0.1:4826/api/health
curl http://127.0.0.1:4826/api/state
curl http://127.0.0.1:4826/api/catalog
```

## Catalog rows

Each row contains these fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Stable 24-character hexadecimal ID derived from source and URL |
| `source` | string | `maps`, `wiki`, or `survivor` |
| `url` | string | Remote content URL resolved during discovery |
| `filename` | string | Decoded, validated filename from the URL |
| `title` | string | Display filename or category title |
| `size` | integer or null | Exact advertised bytes when known; null is not zero |
| `sha256` | string or null | Optional source checksum, used for LFS maps |
| `destination` | string | Path relative to `LIBRARY_ROOT` |
| `installed` | boolean | Added to catalog responses when the destination exists |

Survivor destinations are category directories such as `library/Accounting`.
Installed means a path exists; it does not verify existing content or compare
it against a remote version. Rows are sorted by source and lowercase title.
Wikipedia's latest-edition filtering happens in the browser; the API retains
all discovered editions.

## Mutating requests

Obtain `token` from `/api/state` or `/api/catalog` and send it in the
`X-Library-Token` header. Use a JSON object body and `Content-Type: application/json`.
The body must have a `Content-Length` between 1 and 65,536 bytes. Fetch a new token
after restarting the container. The server does not provide an arbitrary-URL
download endpoint: obtain IDs from its catalog.

The token protects browser actions against cross-origin requests. It is not a
login or an authorization boundary between users on the Library LAN: anyone
who can read the API can obtain it. Responses send no-store, nosniff, and a
same-origin Content Security Policy; no CORS access is configured.

### Refresh sources

```http
POST /api/refresh
Content-Type: application/json
X-Library-Token: <token from state>

{}
```

Returns `202` and `{"ok": true}`. If offline or already refreshing, this is a
no-op rather than a second scan or an immediate connectivity probe. Poll state
for results. The internet monitor automatically requests discovery on recovery.

### Queue downloads

```http
POST /api/download
Content-Type: application/json
X-Library-Token: <token from state>

{"ids": ["<catalog ID>", "<another catalog ID>"]}
```

Submit 1–100 string IDs. Duplicate IDs and already-active jobs are skipped.
Unknown IDs, offline state, unavailable storage, and existing destinations
reject the request before any new jobs in the batch are enqueued. Individual
file sizes are checked again when the worker starts each transfer; acceptance
does not reserve disk space or guarantee success.

A successful request returns `202` and `{"ok": true}`. Requeue a failed or
cancelled ID to retry; its job record is replaced and any usable partial file
is reused. Jobs are not automatically retried after failure or restart.

### Cancel a job

```http
POST /api/cancel
Content-Type: application/json
X-Library-Token: <token from state>

{"id": "<job ID>"}
```

Returns `202` and `{"ok": true}` for a known job. Unknown IDs return `400`.
Cancellation is cooperative: a queued job is cancelled when the worker reaches
it, and an active transfer checks between reads. A blocked network read may
delay cancellation up to its timeout. Cancelling a completed job does not remove
its saved content. This API has no content-deletion endpoint.

## Job records and errors

All jobs have `id`, `title`, `status`, `downloaded`, `total`, `error`, and
`destination`. `total` may be null. Extraction additionally supplies `extracted`
and `extract_total` in bytes. `downloaded` remains the compressed transfer count
while `extracted` tracks PDF bytes. No progress percentage is stored; clients
can calculate one when the relevant total is known.

| State | Meaning |
| --- | --- |
| `queued` | Waiting for the single download worker |
| `downloading` | Transferring data into a partial file |
| `verifying` | Checking size/format and any supplied checksum |
| `extracting` | Writing Survivor PDFs into a staging directory |
| `complete` | Content published to the final destination |
| `failed` | Attempt ended with an error; manual retry is possible |
| `cancelled` | Attempt stopped at a cancellation check |

Errors use `{"error": "description"}`. Handled validation/filesystem errors
return `400`; a missing/wrong token returns `403`; an unknown route returns `404`.
Download failures after queue acceptance are reported in job state rather than
changing the earlier HTTP response. Source failures similarly appear in
`sources`, while health and state endpoints continue responding.
