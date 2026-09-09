# Webserver Container

The webserver container is the main entry point for the Library system. It runs nginx to serve web content and a Python management script (`library.py`) that monitors and controls the other library service containers (wiki, music, ebook, maps, etc.).

## File Structure

```
webserver/
├── Containerfile        # Container build instructions
├── library.py           # Main management script (configures nginx, monitors services)
├── library_setup.yml    # Configuration: containers, services, webserver settings
├── cgi/
│   └── shutdown.py      # CGI script for remote shutdown (port 9999)
└── README.md
```

## Building the Container

Build with the default base image (rasbase - Debian 11 bullseye, arm64):

```bash
podman build -t localhost/webserver:latest .
```

Build with rasbase_trixie (Debian 13 trixie) to test newer packages:

```bash
podman build --build-arg BASE_IMAGE=localhost/rasbase_trixie:latest -t localhost/webserver:latest .
```

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

Each service entry tells library.py how to check if a service is running. The script makes an HTTP request to `internal_ip:internal_port`, looks for `check_text` in the response, and if found, creates a nav bar link pointing to `external_url`:

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

### `containers` — Container definitions

Defines all containers managed by the library system (used by the bootstrap/setup scripts):

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
    ip: 10.88.0.213
    drive_map: '/Library/video:/media:ro'
    command: ''
```

2. Add a service check entry so the webserver can monitor it:

```yaml
services:
  # ... existing services ...
  - name: video
    display_name: "Video Streaming"
    internal_ip: 10.88.0.213
    internal_port: 8096
    external_url: "http://10.1.1.1:8096"
    check_text: "jellyfin"
    timeout: 5
```

3. Rebuild and restart the webserver container to pick up the new config:

```bash
podman build -t localhost/webserver:latest .
podman stop webserver && podman rm webserver
podman run -d --name webserver --ip 10.88.0.201 -p 80:80 -v /Library:/library localhost/webserver:latest
```

## Ports Reference

| Port | Service |
|------|---------|
| 80   | nginx (main web interface) |
| 9999 | Shutdown CGI endpoint |

## Network

All library containers share a podman network with static IPs in the 10.88.0.x range. The webserver acts as the central hub, proxying requests and monitoring the health of other services.
