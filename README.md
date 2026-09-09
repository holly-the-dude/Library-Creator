# Library-Creator

**Your personal, portable digital library — in a box.**

Library-Creator turns a Raspberry Pi into a self-contained knowledge station: your own
little library that fits in the palm of your hand (it doesn't *run* from your hand — that
would just be dumb). It hosts its own WiFi network and serves Wikipedia, a music and
audiobook server, an e-book reader, offline maps with turn-by-turn driving directions, and
any files you can view in a browser (PDFs, images, videos, and more) — all with **no
internet connection required**.

Keep it to yourself or share it with anyone in range. Connect to the WiFi network named
**`library`**, open **`http://library`**, and browse.

> Inspired by the need for accessible information where the internet isn't — in the spirit
> of sites like [survivorlibrary.com](https://www.survivorlibrary.com).

---

## Perfect for

- 🏕️ **Camping trips** — entertainment and information in the great outdoors.
- 🚗 **Road trips** — plug it into the car's power outlet and keep everyone occupied.
- 🎓 **Presentations & classes** — hand out files and resources to a whole room, no network needed.
- 🌾 **Rural or remote areas** — get to information where there simply is no internet.
- 🧟 **Emergencies** — stay informed when the internet is down, whether it's a storm, a
  supply-chain hiccup, or the zombie/asteroid/whatever apocalypse of your choosing.
- 🔒 **Private storage** — keep personal files on a device that never phones home.
- 🤖 **Tech enthusiasts** — because building your own library server is genuinely fun.

---

## Documentation

Pick the guide that matches what you're doing:

| Guide | For you if you want to… |
|-------|--------------------------|
| 📖 **[Usage Guide](docs/USAGE.md)** | **Use** a Library device that's already running — connect, browse Wikipedia, play music, read books, view maps. No technical knowledge needed. |
| 🔧 **[Installation Guide](docs/INSTALL.md)** | **Build/set up** a device: flash the Pi, run the installer, and get a working Library. |
| 🛠️ **[Developer Guide](docs/DEVELOPERS.md)** | **Understand or modify** how it works — architecture, container build pipeline, and adding new services. |

Additional reference:

- [`bootstrap.md`](bootstrap.md) — complete reference for the installer script and its three boot stages.
- Each service has its own README under [`setup_library/files/containers/`](setup_library/files/containers/):
  [hotspot](setup_library/files/containers/hotspot/README.md),
  [webserver](setup_library/files/containers/webserver/README.md),
  [wiki](setup_library/files/containers/wiki),
  [music](setup_library/files/containers/music/README.md),
  [calibre-web](setup_library/files/containers/calibre-web/README.md),
  [library_maps](setup_library/files/containers/library_maps/README.md).

---

## What's included

| Service | Powered by | Client URL |
|---------|-----------|------------|
| 🌐 Web hub | nginx | `http://library` / `http://10.1.1.1` |
| 📚 Wikipedia | [Kiwix](https://kiwix.org/) | `http://10.1.1.1:6902` |
| 🎵 Music | [LMS](https://github.com/epoupon/lms) | `http://10.1.1.1:9099` |
| 📖 E-books | [Calibre-Web](https://github.com/janeczku/calibre-web) | `http://10.1.1.1:8083` |
| 🗺️ Maps | PMTiles + MapLibre + GraphHopper | `http://10.1.1.1:8080` |
| 📶 WiFi hotspot | hostapd + dnsmasq | SSID `library` (open) |

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
                                             └─ graphhopper 10.88.0.213:8989 (routing)
                                        content ⇦ USB drive mounted at /Library
```

Everything runs as Podman containers on the Pi. Content lives on a USB drive, so the
images stay stateless. See the [Developer Guide](docs/DEVELOPERS.md) for the full picture.

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

- Raspberry Pi 3, 4, or 5 with Raspberry Pi OS (64-bit) — Bullseye, Bookworm, or Trixie
- A USB drive for content (reformatted to exFAT during install)
- An optional TFT or HDMI display for boot status
- Internet **during installation only**


---

## Our philosophy

We like things clean and simple. A Library device doesn't track you, doesn't use cookies,
and doesn't phone home — it's a straightforward experience, just like the internet used to
be. Your library is *yours*.
