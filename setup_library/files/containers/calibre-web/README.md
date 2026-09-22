# Calibre-Web Container

This container runs [Calibre-Web](https://github.com/janeczku/calibre-web), a web-based e-book reader that provides a clean interface for browsing, reading, and downloading books stored in a Calibre library. It also includes the `calibredb` CLI tool for adding new books to the library.

## File Structure

```
calibre-web/
├── Containerfile        # Container build instructions
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
    --ip 10.88.0.211 \
    --privileged \
    -p 8083:8083 \
    -v /Library/calibre/books:/books:rw \
    localhost/calibre-web \
    /usr/local/bin/cps
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
| `/usr/local/bin/cps` | pip: calibreweb 0.6.27 | Calibre-Web Python Server (web UI) |
| `/usr/bin/calibredb` | apt: calibre | CLI tool for managing the Calibre library database |

## Dependencies

- **calibre** (apt) — provides `calibredb` for adding/removing/managing books
- **calibreweb** (pip) — the web application itself
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
| 8083 | Calibre-Web interface |

## First-Time Setup

The image preconfigures the library path as `/books` and enables anonymous browsing.
Mount a Calibre library containing `metadata.db` there. If prompted for the library
path after changing configuration, enter `/books`. The default admin credentials are:

- **Username**: admin
- **Password**: admin123

## Exporting the Image

To save the built image as a tar file for deployment:

```bash
podman save -o calibre-web.tar localhost/calibre-web:latest
```

To load it on the target system:

```bash
podman load -i calibre-web.tar
```
