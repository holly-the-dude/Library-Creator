# Library-Creator

**Your personal, portable digital library - in a box.**

[![Donate](https://img.shields.io/badge/Donate-PayPal-blue?logo=paypal)](https://www.paypal.com/ncp/payment/T8MGW39TXCR4J)

> **Don't want to build it yourself?** Get a ready-to-use, pre-configured kit at
> **[librarydepository.com](https://librarydepository.com)** - it arrives ready to go, no assembly required.

Library-Creator turns a Raspberry Pi into a self-contained knowledge station: your own
little library that fits in the palm of your hand (it doesn't *run* from your hand - that
would just be dumb). It hosts its own WiFi network and serves Wikipedia, a music and
audiobook server, an e-book reader, offline maps with turn-by-turn driving directions,
**Meshtastic Communications** for mesh messaging through a USB radio, and
any files you can view in a browser (PDFs, images, videos, and more) - all with **no
internet connection required**.

Keep it to yourself or share it with anyone in range. Connect to the WiFi network named
**`library`**, open **`http://library`**, and browse.

> Inspired by the need for accessible information where the internet isn't - in the spirit
> of sites like [survivorlibrary.com](https://www.survivorlibrary.com).

---

## Perfect for

- <img src="docs/icons/png/camping.png" alt="" height="20" align="absmiddle"> **Camping trips** - entertainment and information in the great outdoors.
- <img src="docs/icons/png/roadtrip.png" alt="" height="20" align="absmiddle"> **Road trips** - plug it into the car's power outlet and keep everyone occupied.
- <img src="docs/icons/png/class.png" alt="" height="20" align="absmiddle"> **Presentations & classes** - hand out files and resources to a whole room, no network needed.
- <img src="docs/icons/png/rural.png" alt="" height="20" align="absmiddle"> **Rural or remote areas** - get to information where there simply is no internet.
- <img src="docs/icons/png/emergency.png" alt="" height="20" align="absmiddle"> **Emergencies** - stay informed when the internet is down, whether it's a storm, a
  supply-chain hiccup, or the zombie/asteroid/whatever apocalypse of your choosing.
- <img src="docs/icons/png/private.png" alt="" height="20" align="absmiddle"> **Private storage** - keep personal files on a device that never phones home.
- <img src="docs/icons/png/tech.png" alt="" height="20" align="absmiddle"> **Tech enthusiasts** - because building your own library server is genuinely fun.

---

## Documentation

Pick the guide that matches what you're doing:

| Guide | For you if you want to… |
|-------|--------------------------|
| <img src="docs/icons/png/usage.png" alt="" height="18" align="absmiddle"> **[Usage Guide](docs/USAGE.md)** | **Use** a Library device that's already running - connect, browse Wikipedia, play music, read books, view maps, and send Meshtastic messages. No technical knowledge needed. |
| <img src="docs/icons/png/install.png" alt="" height="18" align="absmiddle"> **[Install Guide](docs/INSTALL.md)** | **Build/set up** a device: flash the Pi, run the installer, and get a working Library. |
| <img src="docs/icons/png/developer.png" alt="" height="18" align="absmiddle"> **[Dev Guide](docs/DEVELOPERS.md)** | **Understand or modify** how it works - architecture, container build pipeline, and adding new services. |

Additional reference:

- [`bootstrap.md`](bootstrap.md) - complete reference for the installer script and its three boot stages.
- Each service has its own README under [`setup_library/files/containers/`](setup_library/files/containers/):
  [hotspot](setup_library/files/containers/hotspot/README.md),
  [webserver](setup_library/files/containers/webserver/README.md),
  [wiki](setup_library/files/containers/wiki/README.md),
  [music](setup_library/files/containers/music/README.md),
  [calibre-web](setup_library/files/containers/calibre-web/README.md),
  [library_maps](setup_library/files/containers/library_maps/README.md),
  [meshtastic](setup_library/files/containers/meshtastic/README.md),
  [meshflash](setup_library/files/containers/meshflash/README.md).
- [Display role](setup_library/roles/update_display/README.md) - the legacy HTTP status-message helper.
- Historical material: [flasher design notes](setup_library/files/containers/meshflash/flash_tui.md)
  and the [Meshtastic development conversation](setup_library/files/containers/meshtastic/conversation.md).
  Use the service READMEs for current build and operating instructions.

---

## What's included

| Service | Powered by | Client URL |
|---------|-----------|------------|
| <img src="docs/icons/png/web.png" alt="" height="20" align="absmiddle"> Web hub | nginx | `http://library` / `http://10.1.1.1` |
| <img src="docs/icons/png/wiki.png" alt="" height="20" align="absmiddle"> Wikipedia | [Kiwix](https://kiwix.org/) | `http://10.1.1.1:6902` |
| <img src="docs/icons/png/music.png" alt="" height="20" align="absmiddle"> Music | [LMS](https://github.com/epoupon/lms) | `http://10.1.1.1:9099` |
| <img src="docs/icons/png/ebooks.png" alt="" height="20" align="absmiddle"> E-books | [Calibre-Web](https://github.com/janeczku/calibre-web) | `http://10.1.1.1:8083` |
| <img src="docs/icons/png/maps.png" alt="" height="20" align="absmiddle"> Maps | PMTiles + MapLibre + GraphHopper | `http://10.1.1.1:8080` |
| [Meshtastic Communications](docs/USAGE.md#meshtastic-communications) | Meshtastic web client + USB radio; meshflash for firmware setup | `http://library:8086` / `http://10.1.1.1:8086` |
| <img src="docs/icons/png/hotspot.png" alt="" height="20" align="absmiddle"> WiFi hotspot | hostapd + dnsmasq | SSID `library` (open) |

---

## Meshtastic Communications

Connect a Meshtastic radio to the **Raspberry Pi** and use your phone, tablet, or
laptop to send and receive mesh messages through the Library's browser interface.
Open **Meshtastic** from the home page or visit **`http://library:8086`**. Your
browser connects to the Pi over WiFi; the attached radio communicates with other
Meshtastic radios over LoRa. Messaging does not require internet or cellular service.

You need a compatible USB radio, antenna, data cable, and another reachable
Meshtastic node with compatible settings. Use one active browser connection to
the Library radio at a time. If no configured radio responds, the same address
offers the offline firmware setup terminal for supported ESP32 boards.

First startup and connection can take a hot minute while the radio initializes
and discovers nodes. Check the [bridge status](http://10.1.1.1:8086/bridge/status):
`"ready": true` means the radio bridge is ready to connect.

Follow [Meshtastic Communications in the Usage Guide](docs/USAGE.md#meshtastic-communications)
for connecting, sending messages, checking nodes, and setting up a new radio.

---

## How it works (in one picture)

```
 client (phone/laptop) ──WiFi "library"──▶ Raspberry Pi
                                             ├─ hotspot   10.1.1.1  (hostapd + dnsmasq)
                                             ├─ webserver 10.88.0.201:80  (the hub)
                                             ├─ wiki      10.88.0.200:6902
                                             ├─ music     10.88.0.210:5082
                                             ├─ calibre   10.88.0.211:8083
                                             ├─ maps                :8080
                                             ├─ graphhopper 10.88.0.213:8989 (routing)
                                             └─ meshtastic OR meshflash :8086 ⇦ USB radio
                                        content ⇦ USB drive mounted at /Library
```

Everything runs as Podman containers on the Pi. Content lives on a USB drive, so the
images stay stateless. See the [Developer Guide](docs/DEVELOPERS.md) for the full picture.

At startup, a radio that answers the Meshtastic protocol opens the Meshtastic client
on port 8086. If no radio answers, the same address offers firmware setup. Plug the
radio into the **Pi**, not the browser computer. The bridge never flashes firmware;
meshflash requires confirmation. After setup finishes, reboot or rerun the radio
startup check. See [Meshtastic Communications](docs/USAGE.md#meshtastic-communications).

---

## Quick start

```bash
# On a Raspberry Pi running Raspberry Pi OS (64-bit), as root:
cd /root
git clone https://github.com/holly-the-dude/Library-Creator.git
cd Library-Creator
./bootstrap        # choose "1) Fresh Install"
```

The installer handles everything else across three automatic boot stages. Full steps and
requirements are in the [Installation Guide](docs/INSTALL.md).

---

## Requirements

- Raspberry Pi 3, 4, or 5 with Raspberry Pi OS (64-bit) - Bullseye, Bookworm, or Trixie
- A USB drive for content (reformatted to exFAT during install)
- An optional TFT or HDMI display for boot status
- For mesh messaging: a USB Meshtastic radio, suitable antenna, and USB data cable
- For offline firmware installation: an ESP32-family radio supported by meshflash
- Internet **during installation only**


---

## The Idea

We like things clean and simple. A Library device doesn't track you, doesn't use cookies,
and doesn't phone home - it's a straightforward experience, just like the internet used to
be. Your library is *yours*.

---

## Support

If Library-Creator is useful to you, consider [supporting development via PayPal](https://www.paypal.com/ncp/payment/T8MGW39TXCR4J). Thank you!

Prefer a ready-made device? Pre-configured kits are available at [librarydepository.com](https://librarydepository.com).
