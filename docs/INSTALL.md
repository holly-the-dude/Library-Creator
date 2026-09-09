# Installation Guide

This guide is for people who want to build a **Library** device — a self-contained,
offline "library in a box" that runs on a Raspberry Pi and serves Wikipedia, music,
e-books, and offline maps over its own WiFi hotspot. No internet connection is needed
by the people who use it.

If you are a developer wanting to understand or modify how the system is built, read
[DEVELOPERS.md](DEVELOPERS.md) instead. Once your device is running, see
[USAGE.md](USAGE.md) for how to use it.

---

## What you are building

When installation finishes, the Raspberry Pi will:

- Broadcast an **open WiFi network named `library`**.
- Serve a web home page at **`http://library`** (or `http://10.1.1.1`) to anyone who connects.
- Offer Wikipedia, a music player, an e-book reader, and offline maps with turn-by-turn
  driving directions — all offline.
- Show status messages on an attached TFT screen (or HDMI monitor) while it boots.

---

## Requirements

### Hardware

| Item | Notes |
|------|-------|
| Raspberry Pi | Pi 3, Pi 4, or Pi 5 |
| microSD card | 16 GB or larger, for Raspberry Pi OS |
| USB drive | Holds the library content (Wikipedia, music, books, maps). Larger is better — content can be tens of GB |
| Display | A 3.5" TFT, 2.4" TFT, or an HDMI monitor. The display is optional but recommended for seeing boot status |
| Power supply | The official supply for your Pi model |

### Software

- **Raspberry Pi OS** (64-bit, Debian-based). Bullseye, Bookworm, and Trixie are all supported — the installer detects Trixie and applies compatibility fixes automatically.
- Network access **during installation only** (WiFi or Ethernet) so the Pi can download packages and container base images. The finished device does not need internet.
- Root access on the Pi.

---

## Step 1 — Flash Raspberry Pi OS

1. Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) to flash Raspberry Pi OS (64-bit) to your microSD card.
2. In the Imager settings, enable SSH and configure WiFi/Ethernet so you can reach the Pi during setup.
3. Boot the Pi and log in as `root` (or use `sudo -i` to become root).

## Step 2 — Get the installer onto the Pi

Clone this repository into root's home directory:

```bash
cd /root
git clone https://github.com/holly-the-dude/Library-Creator.git
```

That's all you need to do. You'll run the installer directly from the cloned repository in
Step 4 — during First Boot it copies itself to `/root/bootstrap` automatically so the
auto-resume cron job (`/root/bootstrap --auto`) can pick it up after each reboot. You do
not need to copy or `chmod` anything by hand.

## Step 3 — Attach the USB drive

Plug in the USB drive that will hold your library content.

> ⚠️ **Warning:** During a fresh install, any inserted USB drive that is **not** already
> labeled `Library_USB` will be **reformatted** (as exFAT). The installer gives you a
> 30-second countdown to remove it if you plugged in the wrong drive. Make sure the drive
> holds nothing you want to keep.

If your drive is already set up as `Library_USB` from a previous install, it will be left
alone.

## Step 4 — Run the installer

Run it straight from the cloned repository:

```bash
cd /root/Library-Creator
./bootstrap
```

You will see the main menu:

```
╔══════════════════════════════════════════════════╗
║       Library Bootstrap Installer                ║
║       Raspberry Pi Edition                       ║
╚══════════════════════════════════════════════════╝

  Main Menu
──────────────────────────────────────────────────
  1) Fresh Install          - Full installation from scratch
  2) Reinstall              - Remove existing and reinstall
  3) Resume Install         - Continue interrupted install
  4) System Status          - Check installation progress
  5) Advanced Options       - Manual boot stage selection
  q) Quit
──────────────────────────────────────────────────
```

Choose **`1) Fresh Install`**. You will be asked:

1. **Display type** — pick what is attached:
   - `1)` TFT 3.5" (480×320)
   - `2)` TFT 2.4" (320×240)
   - `3)` HDMI, auto-scaled status messages
   - `4)` HDMI desktop (Pi desktop + kiosk browser)
2. **HDMI resolution** (HDMI modes only) — `Auto-scale` is recommended; the Pi reads the monitor's native resolution automatically.
3. **Confirmation** — review the summary and confirm to begin.

## Step 5 — Let it run (three boot stages)

Installation runs in **three stages, each separated by an automatic reboot**. The
installer sets up a cron job that resumes the next stage automatically after each reboot,
so you can leave it alone.

| Stage | What happens |
|-------|--------------|
| **First Boot** | Formats the USB, downloads content, installs packages (Python, Ansible, Podman), configures the display, builds the containers, sets WiFi country, then reboots |
| **Second Boot** | Shows a "configuring" splash, runs the Ansible playbook that installs and wires up all services, then reboots |
| **Third Boot** | Removes the resume cron job, shows the "ready" splash, cleans up temporary network config, and reboots into production mode |

The TFT/HDMI display shows progress messages throughout. Total time depends on your Pi,
network speed, and how much content is downloaded — expect anywhere from 30 minutes to a
couple of hours.

## Step 6 — Verify it worked

When the final boot finishes:

1. On another device (phone, laptop), look for an **open WiFi network named `library`** and connect to it.
2. Open a browser to **`http://library`** (or `http://10.1.1.1`).
3. You should see the Library home page with links to whatever content you installed.

You can also check status directly on the Pi:

```bash
./bootstrap
# choose 4) System Status
```

A healthy install shows First / Second / Third Boot all `COMPLETE`.

---

## Adding map content (tiles + routing)

The Maps service has two independent kinds of data, both stored on the USB under
`/Library/maps`:

| Data | Path on the USB | Purpose |
|------|-----------------|---------|
| **PMTiles** | `/Library/maps/pmtiles/<state>_2025-12.pmtiles` | The map you see and pan/zoom |
| **OSM extract** | `/Library/maps/osm/region.osm.pbf` | Routing data for driving directions |

The viewer auto-discovers any `.pmtiles` files. Driving directions only work when a
routing extract named `region.osm.pbf` is present, and routes only within the area that
extract covers.

The easiest way to load both is the helper script in the `library_maps` container folder,
which downloads a state's tiles **and** its routing extract and activates it for routing:

```bash
cd /root/install/setup_library/files/containers/library_maps
# download Georgia's map tiles + routing data, and make it the active route region:
./scripts/get-state.sh georgia
```

You can load several states' tiles for viewing and choose which one routes:

```bash
./scripts/get-state.sh georgia florida        # tiles + pbf for both
./scripts/get-state.sh --route georgia         # pick georgia as the routing region
```

After changing the routing extract, restart the routing engine so it rebuilds its graph
(the startup playbook also does this automatically on the next boot):

```bash
podman restart graphhopper
```

> ⚠️ **Raspberry Pi memory limit.** Building the routing graph is memory-intensive. On a
> **2 GB Pi, use single-state extracts only** — a multi-state or regional `.pbf` (over
> ~1.5 GB) will run out of memory while importing and routing will never come up. Map
> **viewing** (PMTiles) is unaffected and works at any size. `get-state.sh` warns you if
> an extract looks too large.

---

## Checking progress and logs

- **Status screen:** `./bootstrap` → `4) System Status`
- **Auto-install log:** `/root/install.log`
- **Ansible playbook log:** `/root/installplay.log`

View a log with:

```bash
less /root/installplay.log
```

---

## Reinstalling or starting over

Run `./bootstrap` and choose **`2) Reinstall`**. This:

- Clears the boot-stage flags (`.0boot`, `.firstboot`, `.secondboot`, `.thirdboot`)
- Removes the `install/` and `display/` directories
- Removes all Podman container images

After it finishes, run **`1) Fresh Install`** again.

To resume an interrupted install without wiping anything, choose **`3) Resume Install`**.

---

## Troubleshooting

**The installer didn't resume after a reboot.**
Check that the resume cron entry exists:

```bash
cat /var/spool/cron/crontabs/root
```

It should contain a line calling `/root/bootstrap --auto`. If the system has been up
longer than 5 minutes, auto-resume won't fire — just run `./bootstrap` and pick
`3) Resume Install`.

**The Ansible stage failed.**
Read `less /root/installplay.log` to find the failing task. Then use
`5) Advanced Options → Reset all boot flags` and retry from a fresh install.

**The USB wasn't detected.**
The device must be labeled `Library_USB` and formatted exFAT. A fresh install handles
this for you; if you're mounting an existing drive, confirm the label with
`lsblk -o NAME,FSTYPE,LABEL`.

**The display shows nothing / wrong colors.**
Confirm you picked the correct display type during install. For TFT issues, re-run the
relevant boot stage from `5) Advanced Options`. Serial consoles may not render the
color status messages properly — use SSH or a real terminal.

**I can't see the `library` WiFi network.**
The hotspot needs full control of `wlan0`. If something else (like NetworkManager)
is holding the interface, the hotspot container can't start. See the hotspot notes in
[DEVELOPERS.md](DEVELOPERS.md).

For a deeper reference on every menu option, boot stage, and file location, see
[`bootstrap.md`](../bootstrap.md) in the repository root.
