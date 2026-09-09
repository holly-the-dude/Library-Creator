# Wiki Container

The wiki container runs [kiwix-serve](https://github.com/kiwix/kiwix-tools) to provide offline access to Wikipedia and other ZIM-format wiki content. It serves a web interface on port 6902 that lets users browse the wiki library.

## File Structure

```
wiki/
├── Containerfile                            # Container build instructions
├── kiwix-tools_linux-aarch64-3.8.2.tar.gz  # Pre-compiled kiwix binaries (arm64)
├── start_server                             # Shell script to start kiwix-serve
└── README.md
```

## Building the Container

Build with the default base image (rasbase - Debian 11 bullseye, arm64):

```bash
podman build -t localhost/wiki:latest .
```

Build with rasbase_trixie (Debian 13 trixie) to test newer packages:

```bash
podman build --build-arg BASE_IMAGE=localhost/rasbase_trixie:latest -t localhost/wiki:latest .
```

## Running the Container

```bash
podman run -d \
    --name wiki \
    --ip 10.88.0.200 \
    --privileged \
    -v /Library/wiki:/wiki \
    -p 6902:6902 \
    localhost/wiki:latest
```

- **IP**: 10.88.0.200 (static on the podman network)
- **Port 6902**: kiwix-serve web interface
- **Volume**: `/Library/wiki` mounted at `/wiki` containing ZIM files and wiki.xml library

## How It Works

1. **kiwix-serve** starts and reads `/wiki/wiki.xml` — the library index file
2. The library XML references ZIM files stored in `/wiki/`
3. Users browse wiki content via the web UI at `http://10.88.0.200:6902` (or `http://10.1.1.1:6902` from hotspot clients)

## Wiki Library Structure

The host volume `/Library/wiki` should contain:

```
/Library/wiki/
├── wiki.xml              # Kiwix library XML (lists all available ZIM files)
└── *.zim                 # ZIM files (offline wiki content packages)
```

### Managing the Library

Use `kiwix-manage` inside the container to add/remove ZIM files from the library:

```bash
# Add a new ZIM file to the library
podman exec wiki kiwix-manage /wiki/wiki.xml add /wiki/wikipedia_en.zim

# List current library contents
podman exec wiki kiwix-manage /wiki/wiki.xml show
```

## Kiwix-serve Options

The container starts kiwix-serve with these flags:

| Flag | Description |
|------|-------------|
| `-v` | Verbose output (useful for logs) |
| `-p 6902` | Listen on port 6902 |
| `--nodatealiases` | Disable date-based URL aliases |
| `--library /wiki/wiki.xml` | Use the library XML for content discovery |

## Ports Reference

| Port | Service |
|------|---------|
| 6902 | kiwix-serve web interface |

## Network

| Address | Purpose |
|---------|---------|
| 10.88.0.200 | Wiki container on podman network |
| 10.1.1.1:6902 | External access via hotspot |

## Troubleshooting

- **"Cannot open library file"** — Ensure `/Library/wiki/wiki.xml` exists on the host and the volume is mounted correctly.
- **Empty library page** — Check that the ZIM files referenced in `wiki.xml` actually exist in `/Library/wiki/`. Use `kiwix-manage /wiki/wiki.xml show` to verify.
- **Container exits immediately** — Check logs with `podman logs wiki`. Likely a missing library file or corrupted ZIM.
- **Port not accessible** — Verify the container is running with `podman ps` and the port mapping with `podman port wiki`.
