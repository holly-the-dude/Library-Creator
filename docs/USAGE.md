# Usage Guide

This guide is for **people using a Library device** that is already set up and running.
Think of it as your own personal library that fits in the palm of your hand — Wikipedia,
music and audiobooks, e-books, maps, and your own files, all in one place. You don't need
any technical knowledge, an account, or an internet connection — just a phone, tablet, or
laptop with WiFi.

If you are setting up a new device, see [INSTALL.md](INSTALL.md). If you want to add or
change content or understand how it works, see [DEVELOPERS.md](DEVELOPERS.md).

---

## Connecting to the Library

1. On your phone or laptop, open the WiFi settings.
2. Connect to the open network named **`library`**. There is no password.
3. Open a web browser and go to:

   **`http://library`**

   If that doesn't load, try **`http://10.1.1.1`** or **`http://library.local`**.

You'll land on the **Library home page**, which shows links to every service that is
available on this particular device. Not every device has every service — the home page
only shows what's actually installed.

> The Library has no connection to the internet. Everything you see is stored locally on
> the device. You can use it anywhere, even with no cell signal.

---

## What you can do

The home page acts as a hub. Depending on what's installed, you may see:

| Service | What it is | How to open it |
|---------|-----------|----------------|
| **Wiki** | An offline copy of Wikipedia (and possibly other Kiwix content) | Home page link, or `http://10.1.1.1:6902` |
| **Music** | A web music player with your audio library | Home page link, or `http://10.1.1.1:9099` |
| **eBook Reader** | Browse, read, and download e-books | Home page link, or `http://10.1.1.1:8083` |
| **Maps** | Offline interactive maps with a state/region selector, turn-by-turn driving directions, and a layer on/off panel | Home page link, or `http://10.1.1.1:8080` |

You can share the device with many people at once — up to about 90 devices can connect to
the WiFi hotspot simultaneously.

---

## Using Wikipedia (Wiki)

- Click **Wiki** on the home page.
- Use the search box to look up any topic, just like the real Wikipedia.
- Browse articles, images, and links entirely offline.

The Wiki is served by [Kiwix](https://kiwix.org/). The exact content depends on which
Wikipedia snapshot was loaded onto the device.

---

## Using the Music player

- Click **Music** on the home page. When opened through the home page, you're logged in
  automatically — no username or password needed.
- Browse by artist, album, or track, and play music right in your browser.

If you open the music player **directly** at `http://10.1.1.1:9099` instead of through the
home page, it will show a login form. The credentials are pre-filled:

- **Username:** `music`
- **Password:** `music`

### Listening on a phone app

The music service also speaks the **Subsonic API**, so mobile apps like DSub or
Ultrasonic can connect:

- **Server URL:** `http://10.1.1.1:9099`
- **Username:** `music`
- **Password:** `music`

---

## Using the eBook Reader

- Click **eBook Reader** on the home page.
- Browse the catalog, open a book to read it in your browser, or download it to your
  device.

If prompted to log in, the default account is:

- **Username:** `admin`
- **Password:** `admin123`

(Most reading and downloading works without logging in; the login is mainly for managing
the catalog.)

---

## Using the Maps

- Click **Maps** on the home page.
- Use the dropdown to pick a state or region.
- Pan and zoom the interactive map. Everything — the map tiles, fonts, and icons — is
  served from the device, so it works with no internet.
- **Search** for a place, street, or point of interest with the search box. It searches
  the map area you have loaded, so zoom in near where you're looking for street-level
  results.

### Getting driving directions

If the device has routing data loaded, the map can calculate car routes entirely offline —
no internet, no account, no tracking.

1. In the **Directions** panel (bottom-left), set your **Start** and **Destination**. For
   each one you can either:
   - type coordinates as `latitude,longitude` (e.g. `39.7392,-104.9903`), or
   - click the **Map** button next to it, then click a spot on the map.
2. Click **Route**. The route draws on the map and a turn-by-turn list appears with
   distances. **Clear** resets everything.

Directions only work **within the area that was loaded** on the device (often a single
state). If routing isn't set up, the panel will tell you — the map still works for
viewing.

### Turning map layers on and off

Open the **Layers** panel (bottom-right) to show or hide groups of map features —
**Labels, Roads, Water, Buildings, Land, Boundaries,** and **Points of interest**. This is
handy for decluttering the map or focusing on roads for navigation. The panel updates
automatically when you switch to a different state.

---

## Shutting the device down safely

The Library stores content on a USB drive, so it's best to shut it down properly rather
than just pulling the power. There's a **Shutdown** option built into the web interface —
open it from the home page and confirm.

When you shut down:

1. The screen shows a "shutting down" message.
2. All services stop cleanly.
3. The screen shows **"OK to power off"** — now it's safe to unplug the power.

If the device has a touchscreen, it may also offer a touch control to trigger shutdown.

---

## Making a duplicate or backup microSD card

The Library can **clone itself onto another microSD card** — a quick way to make a backup
or hand copies to other people. The whole system (operating system, services, and
settings) is copied; your **content on the USB drive is not** part of this and stays on the
USB.

> ⚠️ **This erases the card you insert.** The card you put in is completely
> **repartitioned and overwritten** — anything already on it is lost. There is **no
> confirmation prompt**: inserting a suitable card *is* the go-ahead. Only insert a card
> you are happy to wipe, and don't leave other cards/drives plugged in while doing this.

**What you need:** a second microSD card (in a USB card reader) that is **about the same
size as the Pi's boot card** — the device only recognizes a card within ~10% of the boot
card's size. It can be slightly smaller as long as the system data fits.

**Steps:**

1. With the Library **powered off**, insert the blank/target microSD card (via a USB
   reader).
2. Power the Pi on. Early in startup it detects the extra card and begins cloning — the
   display walks through a series of progress screens (checking, partitioning, formatting,
   copying, finalizing). Services do **not** start during a clone.
3. When it finishes, the screen shows a **success** message and asks you to **remove the
   cloned card**. Pull the card out.
4. The Pi then reboots on its own and starts normally as the Library.

If something goes wrong, the screen shows a **failure** message and the Pi shuts down —
just power it back on (without the extra card) to return to normal.

The new card is a bootable, self-contained copy: put it in another Raspberry Pi and it
boots as its own Library.

---

## Frequently asked questions

**Do I need the internet?**
No. The whole point of the Library is that it works completely offline.

**Do I need to install an app?**
No. Everything runs in your web browser.

**Why don't I see Music (or Wiki, or Maps)?**
The home page only lists services that are installed and running on that device. If a
service's content wasn't loaded, its link won't appear.

**I connected to WiFi but `http://library` won't load.**
Try `http://10.1.1.1` directly. If your phone warns that the network "has no internet,"
tell it to stay connected anyway — that's expected for an offline device.

**Can several people use it at once?**
Yes. Many devices can connect and browse at the same time.

**Does it track me or use cookies?**
No. The Library doesn't track you, doesn't use cookies, and doesn't phone home. Your
library is yours — a straightforward experience, just like the internet used to be.

**A page says a service "failed to start" or content is "missing."**
That's a message for whoever set up the device — the content for that service needs to be
added. See [DEVELOPERS.md](DEVELOPERS.md).
