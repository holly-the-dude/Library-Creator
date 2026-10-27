# ChangeLog

Feature highlights and notable improvements from Library-Creator's Git history,
newest first. Dates are commit dates, not versioned release dates. Related commits
are grouped together; routine housekeeping and documentation-only edits are omitted
unless they affect installation or use.

## 2026-10-26 — Clone the operating system or content drive

- **Clone from Downloads:** copy the bootable SD card or `Library_USB` through the browser. File-level copying lets a smaller destination work when it has enough room for the used data plus filesystem overhead. ([ac80fca](https://github.com/holly-the-dude/Library-Creator/commit/ac80fca))
- **Clone service installation:** bootstrap installs the host helper for new installations and adds **Install / Repair Clone** for existing devices. See the [clone guide](setup_library/files/containers/data_download/docs/CLONE.md) for setup and supported layouts. ([ac80fca](https://github.com/holly-the-dude/Library-Creator/commit/ac80fca))
- **Clone progress:** show containers stopping and restarting, bytes copied, and estimated progress for USB content and each SD filesystem. ([6bb8a01](https://github.com/holly-the-dude/Library-Creator/commit/6bb8a01))
- **Destination checks:** protect source and in-use drives, block identified non-SD destinations for OS copies, and require explicit SD-card verification when media type is unknown. Typed destination confirmation remains required before erasure. ([abb4cc7](https://github.com/holly-the-dude/Library-Creator/commit/abb4cc7))
- **Clearer controls:** highlight the destination device in bold, bright green in the erase dialog; use bright green for **Refresh sources** and yellow-orange for the scan button and clone progress. ([6bb8a01](https://github.com/holly-the-dude/Library-Creator/commit/6bb8a01), [abb4cc7](https://github.com/holly-the-dude/Library-Creator/commit/abb4cc7))

## 2026-10-25 — StreetZim, a new music player, and a broader ZIM library

- **StreetZim maps:** add a dedicated offline regional-map viewer with USB GPS support and a **StreetZim maps** download tab. The updated startup configuration shares its GPS feed with the OpenStreetMap viewer.
- **iPod-style music player:** browse and play local music with a click wheel, shuffle, repeat, volume, and seeking. It runs alongside the existing LMS music library.
- **ZIM Library:** expand discovery beyond Wikipedia to the Kiwix catalog, with language, collection, search, and latest-edition filters.
- **Maps and Music menus:** offer both map viewers and both music players from the Library homepage, with service availability shown.
- **Installation from a source copy:** allow Fresh Install and Restart Install from a complete project folder without Git metadata. Reinstall / Upgrade still requires a Git checkout.

Commit: [64ac41e](https://github.com/holly-the-dude/Library-Creator/commit/64ac41e).

## 2026-10-24 — SD-card requirement clarified

- Document a **32 GB minimum SD card** for installation. ([19ec366](https://github.com/holly-the-dude/Library-Creator/commit/19ec366))

## 2026-10-13 — Simpler installation recovery

- **Restart Install:** simplify recovery by clearing installation stage flags and restarting from First Boot; remove the Advanced Options menu. ([a43e2b6](https://github.com/holly-the-dude/Library-Creator/commit/a43e2b6))
- Improve bootstrap/reinstall handling and the installation display artwork. ([2ee2554](https://github.com/holly-the-dude/Library-Creator/commit/2ee2554))
- Prevent the touch-run service from running on HDMI displays. ([eb8e7d7](https://github.com/holly-the-dude/Library-Creator/commit/eb8e7d7))

## 2026-10-12 — Network access and ebook reliability

- **LAN-friendly navigation:** support accessing the Library through `library` or `library.local` when connected to another network. ([dd8cc9c](https://github.com/holly-the-dude/Library-Creator/commit/dd8cc9c))
- Fix Calibre-Web startup hanging on the Raspberry Pi 3B+ and simplify local access by handling the default login automatically. ([9c2988e](https://github.com/holly-the-dude/Library-Creator/commit/9c2988e), [c33d46c](https://github.com/holly-the-dude/Library-Creator/commit/c33d46c))
- Improve reinstall handling and remove the bootstrap archive-password requirement. ([4c9875f](https://github.com/holly-the-dude/Library-Creator/commit/4c9875f), [4a98ea6](https://github.com/holly-the-dude/Library-Creator/commit/4a98ea6))

## 2026-10-11 — Mobile map controls and installer checks

- **Phone-friendly maps:** add bottom navigation and separate panels for map settings, search, GPS, routes, and layers, with improved route-point selection.
- **Flexible checkout location:** let bootstrap find and remember the selected repository instead of relying on one fixed folder name.
- **OS preflight:** check for Trixie and provide an upgrade path before continuing installation stages.

Commit: [53e3303](https://github.com/holly-the-dude/Library-Creator/commit/53e3303).

## 2026-10-10 — Refreshed map and Wikipedia appearance

- Apply the Library theme to the Maps and Kiwix readers, with a hide/show control for map panels. ([ef028e9](https://github.com/holly-the-dude/Library-Creator/commit/ef028e9))

## 2026-10-09 — Upload your own content

- **Local uploads:** send files or folders from a browser to Music, Data, or Ebooks without internet access. Folder structure is preserved, ZIP uploads are extracted, and transfer progress is displayed. ([52a9ff7](https://github.com/holly-the-dude/Library-Creator/commit/52a9ff7))
- **Upload reminders:** explain music rescanning and offer restart reminders after saved data or ebooks; show USB capacity while offline. ([52a9ff7](https://github.com/holly-the-dude/Library-Creator/commit/52a9ff7))
- **Homepage refresh:** bring the main web hub into the same visual style as the other Library tools. ([31af6ab](https://github.com/holly-the-dude/Library-Creator/commit/31af6ab))
- **Reinstall / Upgrade:** update the repository with a fast-forward pull before reinstall cleanup, stopping if the update fails. ([679c704](https://github.com/holly-the-dude/Library-Creator/commit/679c704))

## 2026-10-08 — Restart from the browser

- Add a restart reminder after completed downloads and a **Restart Library** action backed by a host service.
- Add restart support to the main shutdown interface, with graceful container shutdown.

Commit: [e8489c8](https://github.com/holly-the-dude/Library-Creator/commit/e8489c8).

## 2026-10-07 — Download content directly to the Library

- **Downloads app:** browse and download regional PMTiles maps, Wikipedia ZIM files, and Survivor Library PDF collections directly to the USB content drive. Include source status, available-space checks, a download queue, and progress reporting. ([797db49](https://github.com/holly-the-dude/Library-Creator/commit/797db49))
- **Routing downloads:** obtain regional OpenStreetMap extracts from Geofabrik and select **Use after restart** to activate a downloaded region. Startup prepares the selected data and rebuilds the GraphHopper routing graph. ([addab9d](https://github.com/holly-the-dude/Library-Creator/commit/addab9d), [b486bef](https://github.com/holly-the-dude/Library-Creator/commit/b486bef))

## 2026-09-22 — Broader Meshtastic support and offline radio setup

- Expand Meshtastic integration beyond the original Heltec-specific setup to additional compatible devices.
- Add an offline terminal firmware flasher for supported radios that need Meshtastic firmware, with updated setup and usage guides.

Commits: [d26995d](https://github.com/holly-the-dude/Library-Creator/commit/d26995d), [645305c](https://github.com/holly-the-dude/Library-Creator/commit/645305c).

## 2026-09-17 — Meshtastic integration

- Add Meshtastic support, initially targeting the Heltec Wireless Stick Lite V3 ESP32-S3/SX1262 radio. ([544ba97](https://github.com/holly-the-dude/Library-Creator/commit/544ba97))

## 2026-09-14 — GPS hardware guidance

- Document a tested GPS receiver in the usage guide. ([fd2a6f3](https://github.com/holly-the-dude/Library-Creator/commit/fd2a6f3))

## 2026-09-12 — USB GPS and Trixie

- **Live GPS on offline maps:** display the Library's USB GPS position, follow or recenter on a fix, and inspect satellite, connection, and fix-age information.
- Move the Rasbase container base to **Trixie**.

Commit: [a15aeeb](https://github.com/holly-the-dude/Library-Creator/commit/a15aeeb).

## 2026-09-10 — Third-boot setup fix

- Correct missing third-boot touch setup and update the accompanying instructions. ([d679c69](https://github.com/holly-the-dude/Library-Creator/commit/d679c69), [6a5c708](https://github.com/holly-the-dude/Library-Creator/commit/6a5c708))

## 2026-09-09 — Updated icons

- Refresh the Library's service icons. ([6af2b79](https://github.com/holly-the-dude/Library-Creator/commit/6af2b79))

## 2026-09-08 — Initial Library-Creator

- **Portable offline library:** turn a Raspberry Pi into a Wi-Fi hotspot with a browser-based home page, Wikipedia/Kiwix, LMS music and audiobooks, Calibre-Web ebooks, and local files.
- **Offline maps and directions:** combine PMTiles, MapLibre, and GraphHopper for browsing maps and calculating driving routes with locally stored data.
- **Automated setup:** provide a three-stage bootstrap installer, Podman services, USB content storage, and installation, usage, and developer guides.

Commit: [05eb6f2](https://github.com/holly-the-dude/Library-Creator/commit/05eb6f2).
