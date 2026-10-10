# Wiki Container

The wiki container runs [kiwix-serve](https://github.com/kiwix/kiwix-tools) to provide offline access to Wikipedia and other ZIM-format wiki content. It serves a web interface on port 6902 that lets users browse the wiki library.

## File Structure

```
wiki/
├── Containerfile                            # Container build instructions
├── build_theme.py                           # Generate customized CSS resources
├── library-theme.css                        # Library colors and control styles
├── kiwix-tools_linux-aarch64-3.5.0-1.tar.gz  # Pre-compiled kiwix binaries (arm64)
├── start_server                             # Shell script to start kiwix-serve
└── README.md
```

## Library appearance

The catalog, search results, autocomplete suggestions, and reader toolbar share
Data Download's dark purple panels, green accents, and gold (`#f3b41e`) selection
highlights. Catalog filters wrap on small screens. Articles inside the ZIM files
keep their original formatting and colors.

The image build runs `build_theme.py` to append `library-theme.css` to the original
stylesheets embedded in the bundled Kiwix binary. This preserves its layout and
responsive rules. The helper reads the ARM binary as data and checks that all
four expected stylesheets exist before writing any output. If the binary is
upgraded, review the extraction rules and theme against its new UI.

The image sets `KIWIX_SERVE_CUSTOMIZED_RESOURCES` to the generated resource manifest
at `/opt/library-wiki/skin/resources.txt`. Kiwix's
[native custom-resource support](https://github.com/kiwix/libkiwix/blob/main/src/server/internalServer.cpp)
serves these local CSS files, including when the playbooks invoke `kiwix-serve`
directly. No proxy, ZIM modifications, or runtime internet access are needed.

Rebuild the `wiki` image and recreate its container to install the theme.
If an existing browser still shows the old colors, clear its cached files or
perform a hard refresh.

Validate resource generation without running ARM code:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

## Building the Container

Build with the default `localhost/rasbase_master:latest` base (Debian 13 Trixie,
ARM64). Use the appliance's rootful Podman image store:

```bash
sudo podman build -t localhost/wiki:latest -f Containerfile .
```

The parent [`build_pods.sh`](../build_pods.sh) builds this image along with the
other Library services, including both radio images. See the
[build and export workflow](../../../../docs/DEVELOPERS.md#container-build-pipeline)
for preparing the base image and offline tar files. Run the Podman commands below
as root, or prefix them with `sudo`.

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
