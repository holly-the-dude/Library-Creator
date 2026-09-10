# Developer Guide

This guide explains how **Library-Creator** is put together: the architecture, the
container build pipeline, the three-stage install, and how to add or modify services.

If you just want to build a device, read [INSTALL.md](INSTALL.md). If you want to use a
running device, read [USAGE.md](USAGE.md).

---

## What the project is

Library-Creator turns a Raspberry Pi into an **offline "library in a box."** or in the parlance of our times **A Personal Cloud Device** It:

- Runs a self-hosted WiFi **hotspot** (open SSID `library`) so clients need no existing network.
- Serves a **web hub** plus a set of content services, each in its own Podman container.
- Stores all content on a USB drive (label `Library_USB`, exFAT) mounted at `/Library`.
- Requires internet **only at build time**; the finished device is fully offline.

Everything is orchestrated from a single interactive installer script, `bootstrap`, backed
by Ansible playbooks and a set of Podman container definitions.

---
## Future work
- Add GPS usb
- LoRa Text messaging with other Libraries or Meshtastic or both
---

## Architecture overview

```
                        ┌─────────────────────────────────────────────
                        │             Raspberry Pi (host)
   client device        │
   ┌──────────┐  WiFi   │  ┌────────────┐   podman net (10.88.0.0/24)
   │ phone /  │─────────┼─▶│  hotspot   │
   │ laptop   │  SSID   │  │ 10.1.1.1   │   ┌───────────────────────┐
   └──────────┘"library"│  │ hostapd +  │   │ webserver 10.88.0.201 │
                        │  │ dnsmasq    │──▶│ nginx :80 (the hub)  │
                        │  └────────────┘   └──────────┬────────────┘
                        │                              │ monitors
                        │   ┌───────────┐  ┌───────────┴───┐ ┌───────┐
                        │   │wiki       │  │ music         │ │ maps  │
                        │   │10.88.0.200│  │ 10.88.0.210   │ │ :8080 │
                        │   │Kiwix :6902│  │ LMS :5082/9099│ └───┬───┘
                        │   └───────────┘  └───────────────┘     │/api/route
                        │ ┌─────────────────────────────┐   ┌────┴───────────┐
                        │ │calibre-web 10.88.0.211 :8083│   │ graphhopper    │
                        │ └─────────────────────────────┘   │ 10.88.0.213    │
                        │                                   │ :8989 (routing)│
                        │                                   └────────────────┘
                        │        content ⇦ /Library (USB, exFAT)
                        └─────────────────────────────────────────────
```

- The **hotspot** container owns `wlan0`, assigns itself `10.1.1.1/24`, and runs `hostapd`
  (SSID `library`, open, channel 7) plus `dnsmasq` for DHCP (`10.1.1.10–10.1.1.100`) and
  DNS (`library` / `library.local` → `10.1.1.1`).
- The **webserver** is the hub: nginx on port 80 plus `library.py`, which probes each
  service and shows nav links only for the ones that respond.
- Content services each run on a static IP in `10.88.0.0/24` and are reached by clients
  through the mapped host ports.
- The **maps** service is two containers: the `library_maps` web viewer (PMTiles + MapLibre,
  port 8080) and an optional **`graphhopper`** routing engine (`10.88.0.213:8989`). The
  viewer proxies `/api/route` to GraphHopper, so the browser only ever talks to the maps
  web container. Address search is done in-browser against the loaded tiles and routing
  takes lat/lon or map-click points — there is **no geocoder/Photon service**.

### Service / port reference

| Service | Container IP | Internal port | Client URL |
|---------|-------------|---------------|------------|
| Webserver hub | 10.88.0.201 | 80 | `http://10.1.1.1` / `http://library` |
| Wiki (Kiwix) | 10.88.0.200 | 6902 | `http://10.1.1.1:6902` |
| Music (LMS) | 10.88.0.210 | 5082 | `http://10.1.1.1:9099` |
| eBooks (Calibre-Web) | 10.88.0.211 | 8083 | `http://10.1.1.1:8083` |
| Maps (PMTiles + MapLibre) | — | 8080 | `http://10.1.1.1:8080` |
| Maps routing (GraphHopper) | 10.88.0.213 | 8989 | internal, via maps `/api/route` |
| Shutdown endpoint | — | 9999 | internal |

---

## Repository layout

```
Library-Creator/
├── bootstrap                 # Interactive installer (menu-driven, color-coded)
├── bootstrap.md              # Full reference for the installer & boot stages
├── README.md
├── docs/
│   ├── INSTALL.md            # Installation guide (device builders)
│   ├── USAGE.md              # Usage guide (end users)
│   └── DEVELOPERS.md         # This file
└── setup_library/
    ├── 01_install_ansible.yml   # Main playbook: services, systemd, network, display
    ├── 02_mount_usb.yml         # Detect & mount the Library_USB drive
    ├── 03_start_containers.yml  # Start display/hotspot/wiki/music/webserver, report status
    ├── 99_reinstall_pods.yml    # Refresh/reload container images
    └── files/
        ├── Library_USB.tar      # Base content skeleton unpacked onto the USB
        ├── 87-podman-bridge.conflist  # Podman network (static 10.88.0.x IPs)
        └── containers/
            ├── build_pods.sh        # Build every container that has a Containerfile
            ├── create_tar_pods.sh   # Save built images to <name>.tar
            ├── reconstitute.sh      # Reassemble rasbase.tar from split parts, load it
            ├── update_rasbase.sh    # Upgrade the rasbase base image release-by-release
            ├── rasbase00..06        # Split parts of the base image tarball
            ├── hotspot/             # WiFi AP (hostapd + dnsmasq)
            ├── webserver/           # nginx hub + library.py service monitor
            ├── wiki/                # Kiwix server
            ├── music/               # LMS music server
            ├── calibre-web/         # Calibre-Web e-book reader
            └── library_maps/        # PMTiles map viewer (nginx) + MapLibre
                └── graphhopper/     # Optional car-routing engine (built as
                                     #   library_maps-graphhopper:11)
```

Each container directory has its own `README.md` with build/run details — those are the
authoritative reference for each service.

---

## The base image: `rasbase`

All the service containers build `FROM` a shared base image called **`rasbase`** — an
arm64 Raspberry Pi OS / Debian userland. Because a full base image is large, it's stored
in git as **split parts** (`rasbase00` … `rasbase06`) and reassembled at build time.

- **`reconstitute.sh`** — concatenates the split parts back into `rasbase.tar` and loads
  it into Podman:

  ```bash
  cat rasbase?? >> rasbase.tar
  podman load -i rasbase.tar
  ```

- **`update_rasbase.sh`** — upgrades the base image to the newest **stable** Debian
  release that Raspberry Pi OS ships. It reads the current codename from the image,
  detects the target from the Raspberry Pi OS image index, then dist-upgrades one release
  at a time (`bullseye → bookworm → trixie → …`), committing at each hop. Finally it
  flattens the layers into one to reclaim space and verifies the resulting codename.
  It's safe to run repeatedly.

Some containers (e.g. `calibre-web`, `library_maps`) build `FROM localhost/rasbase_master`
for newer packages; others build `FROM localhost/rasbase`. Most accept a
`--build-arg BASE_IMAGE=...` override — see each container's README.

---

## Container build pipeline

Two scripts in `setup_library/files/containers/` do the heavy lifting. Both discover
containers by scanning for subdirectories that contain a `Containerfile` (or `Dockerfile`).

1. **`build_pods.sh`** — for each container folder, removes the old image and rebuilds it:

   ```bash
   cd setup_library/files/containers
   ./build_pods.sh
   ```

   It also builds nested routing subimages: any `*/graphhopper/Containerfile` is built as
   `<parent>-graphhopper:11` (e.g. `library_maps/graphhopper` → `library_maps-graphhopper:11`).

2. **`create_tar_pods.sh`** — saves each built image to `<name>.tar` for offline
   deployment (the finished device loads these tarballs rather than building on the Pi):

   ```bash
   ./create_tar_pods.sh
   ```

Supporting scripts: `load.sh` (load saved tars) and `cp_pod_tars.sh` (copy tars into
place). To build a single container by hand:

```bash
cd setup_library/files/containers/webserver
podman build -t localhost/webserver:latest .
# optionally target the newer base:
podman build --build-arg BASE_IMAGE=localhost/rasbase_master:latest -t localhost/webserver:latest .
```

---

## The install flow (three boot stages)

`bootstrap` is a color-coded, menu-driven script. A fresh install runs in three stages,
each separated by a reboot; a cron entry (`/root/bootstrap --auto`) resumes the next stage
automatically within 5 minutes of boot. Progress is tracked with flag files in `/root`
(`.0boot`, `.firstboot`, `.secondboot`, `.thirdboot`).

| Stage | Key actions | Driven by |
|-------|-------------|-----------|
| **First Boot** | Format USB as `Library_USB` (exFAT, GPT), unpack base content, `apt` install (Python, Ansible, Podman, display drivers), build containers (`reconstitute.sh` → `update_rasbase.sh` → `build_pods.sh`), configure display (TFT via LCD-show, or HDMI via KMS), set WiFi country, install resume cron | `bootstrap` `do_first_boot` |
| **Second Boot** | Show "configuring" splash, run `01_install_ansible.yml` (SSH keys, Podman network, systemd services, display splash services, WiFi, touch input, load container images), verify `shutdown_library.service` | `01_install_ansible.yml` |
| **Third Boot** | Remove resume cron, show "ready" splash, clean up temporary network config, final reboot into production | `bootstrap` `do_third_boot` |

At runtime, `start_library.service` runs `start_library.yml`, which effectively performs
the steps in `03_start_containers.yml`: start the display container, hotspot, then wiki,
music, and webserver — each conditional on its content existing under `/Library`, and each
reporting status to the on-device display via the display container's
`http://127.0.0.1:6901/upload-text` endpoint.

For the complete menu-by-menu and stage-by-stage reference, see
[`bootstrap.md`](../bootstrap.md).

### Display abstraction

The on-screen status messages come from a small "update_display" container that exposes an
HTTP endpoint (`:6901/upload-text`). Ansible tasks POST HTML snippets to it (colored text
in a bordered box). Full-screen splash images are shown via the `displayit <name>.jpg`
helper on the host. TFT panels are driven through goodtft LCD-show; HDMI uses the KMS
driver (auto-scaling from the monitor's EDID, with an optional forced mode via
`LIBRARY_HDMI_RES`).

---

## Content layout on the USB (`/Library`)

Services activate only when their content is present. Expected paths:

| Path | Used by | Notes |
|------|---------|-------|
| `/Library/wiki/wiki.xml` (+ `.zim` files) | Wiki | Kiwix library; `getwiki.sh` fetches content |
| `/Library/music/` | Music | Audio files (mounted read-only in the container) |
| `/Library/.music_data/` | Music | LMS database; seeded from `music_default_data.tar` |
| `/Library/calibre/books/` | eBooks | Calibre library with `metadata.db` |
| `/Library/calibre/put_new_books_here/` | eBooks | Drop zone for `calibredb add` |
| `/Library/library/` | Webserver | Web hub content root |
| `/Library/maps/pmtiles/` | Maps | `.pmtiles` tiles, e.g. `oregon_2025-12.pmtiles` (mounted into the maps container at `/storage/maps/pmtiles/`) |
| `/Library/maps/basemaps-assets/` | Maps | Fonts (glyphs) + sprites for offline labels |
| `/Library/maps/osm/region.osm.pbf` | Maps routing | OSM extract GraphHopper routes on. Absent = viewer only, no directions |
| `/Library/maps/graph-cache/` | Maps routing | GraphHopper's built routing graph (rebuilt when the extract changes) |

If a path is missing, `03_start_containers.yml` posts a "missing content" message to the
display instead of starting that service.

### Maps routing internals

The maps service is started by the runtime `start_library.yml` MAPS block:

- The **viewer** (`library_maps`, `10.88.0.212:8080`) starts whenever `/Library/maps` has
  content. It is always given `--add-host graphhopper:10.88.0.213` so nginx can resolve
  the `/api/route` upstream at startup even when routing is disabled (in that case
  `/api/route` just returns a gateway error and the viewer works normally).
- The **routing engine** (`graphhopper`, `10.88.0.213:8989`) starts only when
  `/Library/maps/osm/region.osm.pbf` exists. GraphHopper imports that extract into
  `/Library/maps/graph-cache` on first start; the playbook waits until the routing API
  answers before continuing, and shows `start_09_building_routing.jpg` /
  `start_09_routing_ready.jpg` splashes.
- **Cache staleness:** the playbook clears `/Library/maps/graph-cache` and forces a
  re-import only when `region.osm.pbf` is newer than the built graph's `properties` file,
  so normal reboots reuse the graph (fast) while a swapped-in extract triggers a rebuild.
- **Loading content:** `library_maps/scripts/get-state.sh <state>` downloads a state's
  PMTiles and OSM extract and activates the extract for routing (see INSTALL.md).

> ⚠️ **2 GB Pi limit.** GraphHopper's import is memory-hungry; on a 2 GB Pi use
> single-state extracts only. A multi-state/regional `.pbf` (>~1.5 GB) OOMs during import
> and routing never comes up (viewing is unaffected). Tune heap via `GH_JAVA_OPTS` /
> the container's `JAVA_OPTS`.

### microSD self-cloning

`start_library.yml` includes a **self-cloning** feature that duplicates the running system
onto a second microSD/USB disk — handy for mass-producing or backing up a finished
Library card. It runs early in startup, **before** any services start.

- **Trigger (implicit):** at boot the playbook finds the boot disk (from `findmnt /` →
  `lsblk PKNAME`) and scans for **another whole disk whose size is within 10% of the boot
  card**. If one is found, cloning begins automatically. There is no prompt — inserting a
  similar-sized card *is* the trigger.
- **Prep:** it shows a 30s warning splash (`66_1_dup_sd.jpg`), then stops all running
  containers (`66_2_dup_sd.jpg`) so the filesystem is quiescent.
- **File-level clone** (splashes `dup_10_checking` → `dup_60_finalize`):
  1. **Fit check** — sums the *used* bytes of `/` and `/boot/firmware` (plus 20% + 1 GiB
     headroom). Because it copies files (not blocks), the destination can be **smaller**
     than the source as long as the used data fits; it aborts if it won't.
  2. **Partition** — writes a DOS table with `sfdisk`, deliberately reusing the **same
     disk label-id (`0xc88f36e7`)** and a fixed 512 MiB boot partition. Keeping the
     label-id means the clone's **PARTUUIDs match the source**, so `cmdline.txt` and
     `/etc/fstab` need no editing and the clone boots unmodified.
  3. **Format** — `mkfs.vfat` (boot) + `mkfs.ext4` (root), copying the source volume
     labels.
  4. **Copy** — `rsync -aHAXx --delete` for `/` (excluding pseudo/volatile dirs and the
     dest mountpoint) and again for `/boot/firmware/`, then recreates the excluded
     mount-point dirs.
  5. **Finalize** — `e2fsck -f -y` then `resize2fs` to grow the root fs to fill the (possibly
     larger) destination partition.
- **Done:** on success it shows `66_3_dup_sd_good.jpg`, waits for the operator to **remove
  the cloned card**, then reboots. On any error the `rescue:` block shows
  `66_3_dup_sd_fail.jpg` and shuts the Pi down.
- **Dependencies:** `rsync`, `sfdisk`, `e2fsck`/`resize2fs`, `mkfs.vfat`/`mkfs.ext4`, `jq`
  (`partclone`/`fsarchiver` are installed by `bootstrap` as well). Source layout assumes
  `mmcblk0` with `p1` boot / `p2` root.

> ⚠️ **Destructive + implicit.** The detected second disk is **repartitioned and
> overwritten** with no confirmation. Any disk within ~10% of the boot-card size that is
> present at boot will be treated as a clone target. Do not leave an unrelated
> similar-sized disk attached. See the end-user steps in
> [USAGE.md](USAGE.md#making-a-duplicate-or-backup-microsd-card).

---

## Adding a new service

1. **Create the container.** Add a folder under `setup_library/files/containers/<name>/`
   with a `Containerfile` (base it on `localhost/rasbase` or `rasbase_master`) and a
   `README.md`. It will be picked up automatically by `build_pods.sh`.
2. **Assign a static IP** in the `10.88.0.0/24` range and a host port.
3. **Register it with the hub.** In the webserver's `library_setup.yml`, add a
   `containers:` entry (name, ports, ip, drive_map, command) and a `services:` entry
   (name, display_name, internal_ip, internal_port, external_url, check_text, timeout).
   The `check_text` is a string `library.py` looks for in the service's HTTP response to
   decide whether to show its nav link.
4. **Start it.** Add a start block to `03_start_containers.yml` (or `start_library.yml`),
   gated on the content existing under `/Library`, and post status to the display.
5. **Package it.** Run `build_pods.sh` then `create_tar_pods.sh` so the image ships as a
   loadable tar. Update the `podman_images` list in `01_install_ansible.yml` /
   `99_reinstall_pods.yml` if the image should be preloaded.

See `setup_library/files/containers/webserver/README.md` for a worked "add a service"
example.

---

## Local development tips

- **Build/iterate on one container** on any arm64 Podman host without a Pi:
  `podman build` + `podman run` using the flags in that container's README.
- **Rebuild everything:** `build_pods.sh` then `create_tar_pods.sh`.
- **Test the hub monitor** by running the webserver container with `/Library` mounted and
  hitting `http://localhost` — links appear as each backing service comes up.
- **Reset a device's install state:** `./bootstrap` → `5) Advanced Options → Reset all
  boot flags`, or `2) Reinstall` to also drop images.
- **Logs:** `/root/install.log` (auto mode), `/root/installplay.log` (Ansible),
  `podman logs <container>` for a specific service.

---

## Conventions

- Container images are tagged `localhost/<name>:latest` and saved as `<name>.tar`.
- Static container IPs live in `10.88.0.0/24`; the hotspot/gateway is `10.1.1.1`.
- All persistent content lives under `/Library` (the USB) so images stay stateless.
- Scripts print color-coded status (`[INFO]`/`[ OK]`/`[WARN]`/`[FAIL]`/`[STEP]`) and
  degrade to plain text when not attached to a terminal.
