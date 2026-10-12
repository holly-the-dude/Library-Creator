# Calibre-Web Container

This container runs [Calibre-Web](https://github.com/janeczku/calibre-web), a web-based e-book reader that provides a clean interface for browsing, reading, and downloading books stored in a Calibre library. It also includes the `calibredb` CLI tool for adding new books to the library.

## File Structure

```
calibre-web/
├── Containerfile
├── initialize-calibre-web.py  # Bounded first-run database initialization
├── configure-calibre-web.py   # Library and trusted-proxy settings
├── start-calibre-web.sh       # Supervises both processes
├── nginx.conf                # Public proxy and automatic admin identity
└── README.md
```

## Building the Container

Build with the default `localhost/rasbase_master:latest` base (Debian 13 Trixie,
ARM64). Use the appliance's rootful Podman image store:

```bash
sudo podman build -t localhost/calibre-web:latest -f Containerfile .
```

The parent [`build_pods.sh`](../build_pods.sh) builds this image along with the
other Library services, including both radio images. See the
[build and export workflow](../../../../docs/DEVELOPERS.md#container-build-pipeline)
for preparing the base image and offline tar files. Run the Podman commands below
as root, or prefix them with `sudo`.

## Running the Container

### Start the Calibre-Web server (normal operation)

```bash
podman run -d \
    --user 0 \
    --restart unless-stopped \
    --stop-timeout 20 \
    --ip 10.88.0.211 \
    --privileged \
    -p 8083:8083 \
    -v /Library/calibre/books:/books:rw \
    localhost/calibre-web \
    /usr/local/bin/start-calibre-web.sh
```

- **IP**: 10.88.0.211 (static on the podman network)
- **Port 8083**: Calibre-Web interface
- **Volume**: `/Library/calibre/books` mounted at `/books` (the Calibre library with `metadata.db`)

### Add new books to the library

```bash
podman run -d \
    --user 0 \
    --ip 10.88.0.212 \
    --privileged \
    -v /Library/calibre/books:/books:rw \
    -v /Library/calibre/put_new_books_here:/incoming:rw \
    localhost/calibre-web \
    /bin/bash -c "calibredb add --with-library=/books -r --automerge=overwrite /incoming/*; rm -rvf /incoming/*"
```

This runs `calibredb` to import books from the `/incoming` directory into the Calibre library, then cleans up the incoming folder.

## Key Components

| Binary | Source | Purpose |
|--------|--------|---------|
| `/usr/local/bin/cps` | pip: latest stable calibreweb | Calibre-Web backend on 127.0.0.1:8084 |
| `/usr/sbin/nginx` | apt: nginx | Public proxy on port 8083; signs visitors in as admin |
| `/usr/bin/calibredb` | apt: calibre | CLI tool for managing the Calibre library database |

## Dependencies

- **calibre** (apt) — provides `calibredb` for adding/removing/managing books
- **calibreweb** (pip, unpinned) — the latest stable release when the install layer runs
- **nginx** (apt) — the local authentication proxy
- **imagemagick** — image processing for book cover thumbnails (used via Wand)
- **ghostscript** — PDF rendering for extracting covers from PDF books

## Volumes

| Host Path | Container Path | Purpose |
|-----------|---------------|---------|
| `/Library/calibre/books` | `/books` | Calibre library (contains `metadata.db` and book files) |
| `/Library/calibre/put_new_books_here` | `/incoming` | Drop zone for new books (used with calibredb add) |

## Network

| Port | Service |
|------|---------|
| 8083 | nginx proxy with automatic admin login |
| 8084 | Calibre-Web backend, bound only to container loopback |

## First-Time Setup

The image preconfigures the library path as `/books`. Mount a Calibre library
containing `metadata.db` there. Every visitor to port 8083 is automatically
authenticated as the existing `admin` user, with full administrator permissions.
This includes OPDS requests. Logging out will authenticate as admin again on the
next request.

nginx overrides `X-Calibre-User` with `admin`; Calibre-Web trusts only the local
proxy at `127.0.0.1`. The backend listens on `127.0.0.1:8084` inside the container.
Use `start-calibre-web.sh` (the image default), rather than invoking `cps` directly.
The startup script reapplies the appliance port and proxy settings on each start.

Proxy authentication does not submit or embed a password. A fresh database still
has the upstream default credentials:

- **Username**: admin
- **Password**: admin123

## Updating Calibre-Web

The package is unpinned and installed with `pip --upgrade`. Normal image builds
can reuse the pip layer; to check PyPI again, rebuild without the layer cache:

```bash
sudo podman build --no-cache -t localhost/calibre-web:latest -f Containerfile .
```

Recreate the server container after rebuilding, then export the new image for
offline deployment.

## Exporting the Image

To save the built image as a tar file for deployment:

```bash
podman save -o calibre-web.tar localhost/calibre-web:latest
```

To load it on the target system:

```bash
podman load -i calibre-web.tar
```
