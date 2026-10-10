# Webserver Container

The webserver container is the main entry point for the Library system. It runs nginx to serve web content and a Python management script (`library.py`) that checks the other Library services and updates navigation links. Container startup
and radio selection are handled by the runtime
[`start_library.yml`](../../start_library.yml) playbook.

## File Structure

```
webserver/
├── Containerfile        # Container build instructions
├── library.py           # Main management script (configures nginx, monitors services)
├── style.css            # Downloader-matched theme embedded in generated pages
├── assets/library.jpg   # Header logo copied from ../../display/library.jpg
├── library_setup.yml    # Configuration: containers, services, webserver settings
├── cgi/
│   └── shutdown.py      # CGI script for remote shutdown (port 9999)
└── README.md
```

## Appearance and file browsing

The top-left header links home and shows the supplied `display/library.jpg`
beside **Offline depository, in your hands**. The image
keeps its original proportions and scales down on phones. A copy is bundled at
`assets/library.jpg` so the webserver can be built from its own directory; copy
the source image there again when updating the logo. Nginx serves it at
`/library-brand.jpg` from `/usr/share/library-web/library.jpg` in the container,
so regenerating pages on the USB drive does not remove the logo.

The home page and generated folder pages match the Data Download interface:
dark-purple backgrounds, rounded panels, green accents, the same typography,
and gold (`#f3b41e`) navigation highlighting. Home remains highlighted while
browsing the local library. Available services appear as wrapping navigation
buttons, with Downloads before Shutdown. Folder markers use light blue; file
rows show their type and highlight on hover or keyboard focus. Empty folders
show a message. The layout adapts to phones and includes a skip-to-files link.

Folder pages show the current folder name and a **Back to parent folder** button
above the **File / folder** table header. Top-level folders show **Back to
library** instead. These links work even when opening a folder page directly;
they do not depend on browser history. The home page has no Back button.

The theme lives in `style.css` beside `library.py`. The generator embeds it in
each page, so the interface needs no external fonts, JavaScript, or network
assets. File links and detected service links still open in a new tab; folder
links stay in the library. Service discovery, music proxying, and the Shutdown
destination retain their existing behavior.

Rebuild and recreate the webserver container to apply the theme. On startup,
the changed template regenerates existing home and folder pages even when the
content file count is unchanged. When copying the generator manually, copy
`style.css` alongside it, then run `python3 /root/library.py` in the container.

## Building the Container

Build with the default `localhost/rasbase_master:latest` base (Debian 13 Trixie,
ARM64). Use the appliance's rootful Podman image store:

```bash
sudo podman build -t localhost/webserver:latest -f Containerfile .
```

The parent [`build_pods.sh`](../build_pods.sh) builds this image along with the
other Library services, including both radio images. See the
[build and export workflow](../../../../docs/DEVELOPERS.md#container-build-pipeline)
for preparing the base image and offline tar files. Run the Podman commands below
as root, or prefix them with `sudo`.

## Running the Container

```bash
podman run -d \
    --name webserver \
    --ip 10.88.0.201 \
    -p 80:80 \
    -v /Library:/library \
    localhost/webserver:latest
```

- **IP**: 10.88.0.201 (static on the podman network)
- **Port 80**: nginx web server
- **Port 9999**: shutdown CGI endpoint
- **Volume**: `/Library` mounted at `/library` for access to all library content

## Configuration: library_setup.yml

The config file (`/root/library_setup.yml` inside the container) defines three sections:

### `webserver` — Webserver-specific settings

```yaml
webserver:
  library_path: /library/library
  web_path: /library/web
  host_ip: 10.1.1.1
  nginx:
    listen_port: 80
    server_names:
      - localhost
      - library
      - library.local
      - 10.1.1.1
  shutdown_port: 9999
```

### `services` — Services to monitor

Each service entry tells library.py how to check if a service is running. The script makes an HTTP request to `internal_ip:internal_port` with an optional
`check_path` (default: the root path), looks for `check_text` in the response, and if found, creates a nav bar link pointing to `external_url`:

```yaml
services:
  - name: wiki
    display_name: "Wiki"
    internal_ip: 10.88.0.200
    internal_port: 6902
    external_url: "http://10.1.1.1:6902"
    check_text: "Kiwix"
    timeout: 5

  - name: ebook
    display_name: "eBook Reader"
    internal_ip: 10.88.0.211
    internal_port: 8083
    external_url: "http://10.1.1.1:8083"
    check_text: "Calibre-Web"
    timeout: 10
```

### Meshtastic and setup share one navigation link

The radio check uses the published **host** port because startup can select
Meshtastic or meshflash:

```yaml
  - name: meshtastic
    display_name: "Meshtastic"
    internal_ip: 10.1.1.1
    internal_port: 8086
    check_path: /
    external_url: "http://10.1.1.1:8086"
    check_text: "<html"
    timeout: 5
```

This checks whether a page is available; it does not prove that the radio is ready.
The bridge exposes readiness separately at `/bridge/status`. The runtime playbook
selects the client for a responding USB radio, or firmware setup if none responds.
It owns the two mutually exclusive containers at `10.88.0.214`. Do not add a
second static radio definition here. See the
[radio deployment notes](../meshflash/README.md#library-startup-integration),
including the required match between published and listening ports.

Rebuild and recreate the webserver after updating its bundled configuration so
existing installations use this shared-port check.

### Downloads navigation

The **Downloads** tab follows Meshtastic and precedes Shutdown. It links to
**http://10.1.1.1:4826** and checks `/api/health` on that published host port.
The check succeeds even while the downloader is waiting for internet, so users
can reach its offline status screen. If the service is unavailable, its link is
omitted, like the other service links.

The startup playbook starts the installed `localhost/data_download:latest` image
before generating the homepage, with `/Library:/Library` and `4826:4286` port
publication. See the [downloader setup instructions](../data_download/README.md).
Rebuild/recreate this webserver and deploy the updated startup playbook on existing
installations. `library.py` regenerates navigation on its next run when available
services change, even if the library file count has stayed the same. It does not
poll services continuously; start the downloader before running the generator.

Run the offline navigation regression checks from the repository root:

```sh
python3 -m unittest discover -s setup_library/tests -p test_download_navigation.py -v
```

### `containers` — Container definitions

Records static container metadata for setup scripts. This section does not itself
start containers; keep the runtime playbook in sync when adding a service:

```yaml
containers:
  - name: wiki
    ports: '6902:6902'
    ip: 10.88.0.200
    drive_map: '/Library/wiki:/wiki'
    command: '/bin/sh -c kiwix-serve -v -p 6902 --nodatealiases --library /wiki/wiki.xml'

  - name: webserver
    ports: '80:80'
    ip: 10.88.0.201
    drive_map: '/Library:/library'
    command: '/usr/bin/python3 /root/library.py;sleep infinity'
```

## Adding a New Service

To add a new service (e.g., a video streaming server):

1. Add the container definition to the `containers` section:

```yaml
containers:
  # ... existing containers ...
  - name: video
    ports: '8096:8096'
    ip: 10.88.0.215
    drive_map: '/Library/video:/media:ro'
    command: ''
```

2. Add a service check entry so the webserver can monitor it:

```yaml
services:
  # ... existing services ...
  - name: video
    display_name: "Video Streaming"
    internal_ip: 10.88.0.215
    internal_port: 8096
    external_url: "http://10.1.1.1:8096"
    check_text: "jellyfin"
    timeout: 5
```

3. Add the service startup task to [`start_library.yml`](../../start_library.yml),
   including its content mount and published port. Deploy the updated playbook.
4. Rebuild and restart the webserver container to pick up the new config:

```bash
podman build -t localhost/webserver:latest .
podman stop webserver && podman rm webserver
podman run -d --name webserver --ip 10.88.0.201 -p 80:80 -v /Library:/library localhost/webserver:latest
```

## Ports Reference

| Port | Service |
|------|---------|
| 80   | nginx (main web interface) |
| 4826 | Downloads (separate container; forwards to internal port 4286) |
| 9999 | Shutdown CGI endpoint |

## Network

All library containers share a podman network with static IPs in the 10.88.0.x range. The webserver acts as the central hub, proxying requests and monitoring the health of other services.
