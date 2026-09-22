# Installation Guide

This guide is for people who want to build a **Library** device - a self-contained,
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
  driving directions - all offline.
- Show status messages on an attached TFT screen (or HDMI monitor) while it boots.
- Offer **Meshtastic Communications** at `http://library:8086`: the radio client when a USB radio answers,
  or the firmware setup terminal when no Meshtastic radio answers.

---

## Requirements

### Hardware

| Item | Notes |
|------|-------|
| Raspberry Pi | Pi 3 (dont expect speed), Pi 4, or Pi 5 (2gb works) |
| microSD card | 16 GB or larger, for Raspberry Pi OS and install files|
| USB drive | Holds the library content (Wikipedia, music, books, maps). Larger is better - content can ginormous |
| Display | A 3.5" TFT, 2.4" TFT, or an HDMI monitor. The display is optional but recommended for seeing boot status |
| Power supply | The official supply for your Pi model |
| Meshtastic radio (optional) | USB radio, matching antenna and data cable; ESP32 required for the bundled firmware flasher |
| GPS receiver (optional) | USB NMEA receiver for maps; this is a separate device from the Meshtastic radio |

### Software

- **Raspberry Pi OS** (64-bit, Debian-based). Bullseye, Bookworm, and Trixie are all supported - the installer detects Trixie and applies compatibility fixes automatically.
- Dont skimp select the "Raspberry Pi Desktop, cause you can hook up a monitor mouse,keyboard an still use this thing
- Network access **during installation only** (WiFi or Ethernet) so the Pi can download packages and container base images. The finished device does not need internet.
- Root access on the Pi.

---

## Step 1 - Flash Raspberry Pi OS

1. Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) to flash Raspberry Pi OS (64-bit) to your microSD card.
2. In the Imager settings, enable SSH and DO NOT configure wifi.
1. insert the microsd card
2. plug in your usb drive
3. install the tft display or hdmi video
4. connect the pi's ethernet port to an active port on your router
3. Boot the Pi and log in as `root` (or use `sudo bash` to become root).

## Step 2 - Get the installer onto the Pi

Clone this repository into root's home directory:

```bash
cd /root
git clone https://github.com/holly-the-dude/Library-Creator.git
```

That's all you need to do. You'll run the installer directly from the cloned repository in
Step 4 - during First Boot it copies itself to `/root/bootstrap` automatically so the
auto-resume cron job (`/root/bootstrap`) can pick it up after each reboot. You do
not need to copy or `chmod` anything by hand.

## Step 3 - Attach the USB drive

Plug in the USB drive that will hold your library content.

> ⚠️ **Warning:** During a fresh install, any inserted USB drive that is **not** already
> labeled `Library_USB` will be **reformatted** (as exFAT). The installer gives you a
> 30-second countdown to remove it if you plugged in the wrong drive. Make sure the drive
> holds nothing you want to keep.

If your drive is already set up as `Library_USB` from a previous install, it will be left
alone.

## Step 4 - Run the installer

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

1. **Display type** - pick what is attached:
   - `1)` TFT 3.5" (480×320)
   - `2)` TFT 2.4" (320×240)
   - `3)` HDMI, auto-scaled status messages
   - `4)` HDMI desktop (Pi desktop + kiosk browser)
2. **HDMI resolution** (HDMI modes only) - `Auto-scale` is recommended; the Pi reads the monitor's native resolution automatically.
3. **Confirmation** - review the summary and confirm to begin.

## Step 5 - Let it run (three boot stages)

Installation runs in **three stages, each separated by an automatic reboot**. The
installer sets up a cron job that resumes the next stage automatically after each reboot,
so you can leave it alone.
Once it starts running its borring lots of updates and installs, and time. If you have chosen a fast microsd card then it will be faster.
you can always get a cup of coffee!

| Stage | What happens |
|-------|--------------|
| **First Boot** | Formats the USB, downloads content, installs packages (Python, Ansible, Podman), configures the display, builds the containers, sets WiFi country, then reboots |
| **Second Boot** | Shows a "configuring" splash, runs the Ansible playbook that installs and wires up all services, then reboots |
| **Third Boot** | Removes the resume cron job, shows the "ready" splash, cleans up temporary network config, and reboots into production mode |

The TFT/HDMI display shows progress messages throughout. Total time depends on your Pi,
network speed, and how much content is downloaded - expect anywhere from 30 minutes to a
couple of hours.

## Step 6 - Verify it worked

When the final boot finishes:

1. On another device (phone, laptop), look for an **open WiFi network named `library`** and connect to it.
2. Open a browser to **`http://library`** (or `http://10.1.1.1`).
3. You should see the Library home page with links to whatever content you installed.

You can also check status directly on the Pi:

```bash
./bootstrap
# choose 4) System Status
```

The status screen reports stage flags as `COMPLETE`. These flags alone do not
prove every task succeeded; check the installation logs if services are missing.

---

## Set up the Meshtastic radio

For messaging after setup, follow [Meshtastic Communications](USAGE.md#meshtastic-communications).
Prepare a second reachable radio for an exchange of test messages. Set the LoRa
region for the installation location and match your group's radio/channel settings.
The bridge preserves an already-configured region; for an unset radio it applies
`LORA_REGION` (default `US`). Configure that default before first provisioning an
appliance elsewhere; see the [radio defaults](../setup_library/files/containers/meshtastic/README.md#hardware-and-firmware).

Both radio images and their launchers use port 8086. When updating an existing
installation, rebuild the image, deploy the updated playbook and recreate the
container; see [flasher upgrades](../setup_library/files/containers/meshflash/README.md#port-configuration-and-upgrades).

1. Plug the radio into the **Pi** with a data-capable USB cable and attach its antenna.
2. Open `http://library:8086` (or `http://10.1.1.1:8086`). A radio already running
   Meshtastic opens the web client; choose an **HTTP** connection to `library:8086`.
3. If the setup terminal appears, select the radio's serial port, exact board model,
   firmware version, and operation. Erase & install removes the radio's settings and keys.
4. Wait for completion and let the radio reboot. Reboot the Pi, or run as root over SSH:

   ```sh
   ansible-playbook /root/start_library.yml --tags mesh
   ```

The check stops both radio containers, probes again, and starts the selected service.
Do not run it while a flash is in progress. Selection happens at startup or on this
command, not continuously while the browser is open. No responding radio also offers
setup when no radio is attached; the firmware menu cannot flash until one is connected.

The device menu can include a GPS receiver. Check `ls -l /dev/serial/by-id/` on the Pi;
port numbers can change. With multiple responding radios, select one explicitly using
`-e meshtastic_device=/dev/serial/by-id/your-radio` on the startup command.

Both `localhost/meshtastic:latest` and `localhost/meshflash:latest` must be built or
loaded locally. The installer calls `build_pods.sh`, which requires both build folders.
The flasher bundles firmware while online; no internet is needed for bundled releases.
See the [Meshtastic README](../setup_library/files/containers/meshtastic/README.md) and
[meshflash README](../setup_library/files/containers/meshflash/README.md) for device
mappings, supported firmware, SSH access, and upgrades from older images.

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
> **2 GB Pi, use single-state extracts only** - a multi-state or regional `.pbf` (over
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
longer than 5 minutes, auto-resume won't fire - just run `./bootstrap` and pick
`3) Resume Install`.

**The Ansible stage failed.**
Read `less /root/installplay.log` to find the failing task. Then use
`5) Advanced Options → Reset all boot flags` and retry from a fresh install.

**Port 8086 shows firmware setup even though a radio is connected.**
The radio did not complete a Meshtastic handshake. Check its USB cable, firmware,
and whether another serial client has the port open. A recognized ESP chip or USB
adapter is not proof that Meshtastic is running. The bridge never installs firmware
automatically. See the radio READMEs linked above.

**The USB storage wasn't detected.**
The device must be labeled `Library_USB` and formatted exFAT. A fresh install handles
this for you; if you're mounting an existing drive, confirm the label with
`lsblk -o NAME,FSTYPE,LABEL`.

**The display shows nothing / wrong colors.**
Confirm you picked the correct display type during install. For TFT issues, re-run the
relevant boot stage from `5) Advanced Options`. Serial consoles may not render the
color status messages properly - use SSH or a real terminal.

**I can't see the `library` WiFi network.**
The hotspot needs full control of `wlan0`. If something else (like NetworkManager)
is holding the interface, the hotspot container can't start. See the hotspot notes in
[DEVELOPERS.md](DEVELOPERS.md).

For a deeper reference on every menu option, boot stage, and file location, see
[`bootstrap.md`](../bootstrap.md) in the repository root.
