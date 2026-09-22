# Usage Guide

This guide is for **people using a Library device** that is already set up and running.
Think of it as your own personal library that fits in the palm of your hand - Wikipedia,
music and audiobooks, e-books, maps, Meshtastic Communications, and your own files,
all in one place. Meshtastic needs a radio connected to the Library Pi. You don't need
any technical knowledge, an account, or an internet connection - just a phone, tablet, or
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
available on this particular device. Not every device has every service - the home page
only shows what's actually installed.

> The Library has no connection to the internet. Everything you see is stored locally on
> the device. You can use it anywhere, even with no cell signal.

---

## What you can do

The home page acts as a hub. Depending on what's installed, you may see:

| Service | What it is | How to open it |
|---------|-----------|----------------|
| **Wiki** | [Zim File Downloads](https://dumps.wikimedia.org/kiwix/zim/wikipedia/) An offline copy of Wikipedia (and possibly other Kiwix content) | Home page link, or `http://10.1.1.1:6902` |
| **Music** | A web music player with your audio library | Home page link, or `http://10.1.1.1:9099` |
| **eBook Reader** | Browse, read, and download e-books | Home page link, or `http://10.1.1.1:8083` |
| **Maps** | Offline interactive maps with a state/region selector, turn-by-turn driving directions, and a layer on/off panel | Home page link, or `http://10.1.1.1:8080` |
| **[Meshtastic Communications](#meshtastic-communications)** | Send and receive mesh messages through the Pi's USB radio; includes firmware setup | Home page link, or `http://10.1.1.1:8086` |

You can share the device with many people at once - up to about 90 devices can connect to
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
  automatically - no username or password needed.
- Browse by artist, album, or track, and play music right in your browser.

If you open the music player **directly** at `http://10.1.1.1:9099` instead of through the
home page, it will show a login form. The credentials are pre-filled if not then here is the details:

- **Username:** `music`
- **Password:** `music`

### Adding music
- copy your music to /Library/music or E:\Library\music or /Volumes/Library_USB/music
- once there reboot and in the music app click the gear icon and scan for new music
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

## Adding books
- copy files to /Library/calibre/put_new_books_here/ or E:\caliber\put_new_books\here or /Volumes/Library_USB/Library/calibre/put_new_books_here/

---

## Using the Maps

- Click **Maps** on the home page.
- Use the dropdown to pick a state or region.
- Pan and zoom the interactive map. Everything - the map tiles, fonts, and icons - is
  served from the device, so it works with no internet.
- **Search** for a place, street, or point of interest with the search box. It searches
  the map area you have loaded, so zoom in near where you're looking for street-level
  results.

### Using a USB GPS

Connect the GPS receiver to the **Library device**, then open Maps. A fresh position
automatically updates the map with a **green pin**. The **Use GPS** button
appears when a serial receiver candidate is detected; use it to recenter and follow
the GPS again after panning. Manual latitude/longitude entry still works.

A **red pin** marks manually entered coordinates or the last known GPS position when
the fix is lost. It does not mean a current GPS location. Open **GPS status** for
live latitude/longitude, satellite counts, fix age, and device/connection details.
This button is also available when no GPS is found, to help troubleshoot.

Place the receiver where it has a clear view of the sky and allow time for a fix.
Everyone viewing the map sees the location of the Library's receiver. GPS works
offline, but map details are only available for regions loaded on the Library.

#### Tested GPS devices:
- [VK-172 USB GPS](https://www.amazon.com/dp/B078Y597M6) Module G-mouse,

### Getting driving directions

If the device has routing data loaded, the map can calculate car routes entirely offline -
no internet, no account, no tracking.

1. In the **Directions** panel (bottom-left), set your **Start** and **Destination**. For
   each one you can either:
   - type coordinates as `latitude,longitude` (e.g. `39.7392,-104.9903`), or
   - click the **Map** button next to it, then click a spot on the map.
2. Click **Route**. The route draws on the map and a turn-by-turn list appears with
   distances. **Clear** resets everything.

Directions only work **within the area that was loaded** on the device (often a single
state). If routing isn't set up, the panel will tell you - the map still works for
viewing.

### Turning map layers on and off

Open the **Layers** panel (bottom-right) to show or hide groups of map features -
**Labels, Roads, Water, Buildings, Land, Boundaries,** and **Points of interest**. This is
handy for decluttering the map or focusing on roads for navigation. The panel updates
automatically when you switch to a different state.

---

## Meshtastic Communications

Use the Library's attached Meshtastic radio to exchange short text messages with
other Meshtastic nodes. Your phone or laptop reaches the Pi over WiFi; the Pi's
USB radio carries messages over LoRa. The other person needs a reachable
Meshtastic radio with compatible settings. They do not need to join the Library's
WiFi network. Messaging works without internet or cellular service.

### Connect to the Library radio

1. Attach the radio's antenna and connect the radio to the **Library Pi** with a
   USB data cable. Start the Pi with the radio attached.
2. Join the Library WiFi, then open **Meshtastic** on the home page or visit
   **`http://library:8086`**. If that name does not resolve, use **`http://10.1.1.1:8086`**.
3. Wait for radio initialization and discovery, normally about a minute after the
   radio connects. If a firmware terminal appears, follow the setup steps below.
4. In the web client, add an **HTTP** connection. Enter **`library:8086`**, or
   **`10.1.1.1:8086`** if you opened the page using that IP. Leave TLS/HTTPS off
   for the normal HTTP hotspot connection.
5. Connect and let the client load the radio's configuration and node list.

**Give it a hot minute on first startup or connection.** The bridge loads the
radio's configuration and waits for node discovery, which defaults to 60 seconds
in addition to connection time. Open
[http://10.1.1.1:8086/bridge/status](http://10.1.1.1:8086/bridge/status)
to check, and refresh the page for an updated result:

- `"ready": true` — the radio bridge is ready; return to the web client and connect.
- `"ready": false` — it is still initializing or the radio is unavailable. The
  `error` field gives the current waiting message or connection error.

This status page is available while the Meshtastic bridge is running; it is not
part of the firmware setup terminal.

Select **HTTP** to reach the Pi's radio. The browser's Serial option accesses USB
on the computer running the browser. Use the locally served page on the Library;
an internet-hosted client is not needed.

Use **one active radio client/tab at a time**, even though other Library services
can serve many visitors. Everyone using this connection operates the same radio
and sends under its node identity. Library startup assigns a name such as
`library0001`, avoiding names already known to the radio.

### Send and receive messages

1. Ask the operator which channel your group uses, then open that channel's
   conversation in the web client.
2. Enter a short text message and send it. Incoming messages received by the radio
   appear in the conversation while you are connected.
3. To contact a particular node, select it from the node list and use its messaging
   action to open a direct conversation.
4. For a first test, have someone with another configured radio send a reply.
   Seeing a node in the list alone does not prove it is still reachable.

The radios must use a suitable LoRa region, matching modem settings and frequency
slot. For channel messages, the channel name and key must also match. Ask the
operator to configure these before testing; changing them affects the shared
radio. See the official [LoRa configuration](https://meshtastic.org/docs/configuration/radio/lora/)
and [channel configuration](https://meshtastic.org/docs/configuration/radio/channels/)
references when preparing the radios online.

Channel messages are shared with others configured for that channel. The default
channel key is publicly known; use your group's configured channel for group
communications. The web client's map may require internet tiles; the Library's
separate **Maps** service provides offline maps.

On the normal HTTP hotspot, browser message history may be temporary and disappear
when the page reloads. Radio settings remain on the radio; do not use the browser
as the only record of messages you need to keep.

### If the firmware setup terminal appears

The Pi did not find a responding Meshtastic radio. If your radio already worked,
check its cable and ask the operator to check the connection before reinstalling
firmware. Setup also appears when no radio is plugged in.

1. Connect a supported ESP32-family radio to the Pi with a USB data cable.
2. Use arrows, Tab and Enter to select the radio's serial port and exact board model.
   A GPS receiver can also appear in this list; ask the operator if the port is unclear.
3. Select a bundled firmware version and confirm the operation. **Erase & install
   deletes existing settings and keys.** Nothing is flashed just by connecting a radio.
4. Wait until flashing completes and the radio reboots. Ask the operator to reboot
   the Pi or run the [radio startup check](INSTALL.md#set-up-the-meshtastic-radio).
   Then reopen the same web address and connect using HTTP as described above.

Closing the browser leaves a flash running. Reconnect to see its status; keep the
radio plugged in and the Pi powered until completion. Startup selection does not
switch automatically while the terminal is open. The flasher supports bundled
ESP32 firmware; nRF52/RP2040/UF2 flashing is not implemented. If the browser terminal
is unavailable, the operator can use the [SSH fallback](../setup_library/files/containers/meshflash/README.md#ssh-fallback).

### Connection and messaging checks

| What you see | What to check |
| --- | --- |
| Page does not load | Stay connected to Library WiFi and try `http://10.1.1.1:8086`. Ask the operator to check the service if it still fails. |
| Page loads but radio will not connect | Use HTTP with the same address and port as the page; close other radio tabs and allow initialization to finish. |
| No nodes or replies | Check that another radio is powered, reachable, and configured for the same mesh/channel. Ask the operator to check settings and antenna placement. |
| Connection lost after USB reconnection | Ask the operator to rerun radio selection after the board boots; its USB device mapping may have changed. |

For serial diagnostics, startup backups, and administration, see the
[Meshtastic container guide](../setup_library/files/containers/meshtastic/README.md).

---

## Shutting the device down safely

The Library stores content on a USB drive, so it's best to shut it down properly rather
than just pulling the power. There's a **Shutdown** option built into the web interface -
open it from the home page and confirm.

When you shut down:

1. The screen shows a "shutting down" message.
2. All services stop cleanly.
3. The screen shows **"OK to power off"** - now it's safe to unplug the power.

If the device has a touchscreen, it may also offer a touch control to trigger shutdown.

---

## Making a duplicate or backup microSD card

The Library can **clone itself onto another microSD card** - a quick way to make a backup
or hand copies to other people. The whole system (operating system, services, and
settings) is copied; your **content on the USB drive is not** part of this and stays on the
USB.

> ⚠️ **This erases the card you insert.** The card you put in is completely
> **repartitioned and overwritten** - anything already on it is lost. There is **no
> confirmation prompt**: inserting a suitable card *is* the go-ahead. Only insert a card
> you are happy to wipe, and don't leave other cards/drives plugged in while doing this.

**What you need:** a second microSD card (in a USB card reader) that is **about the same
size as the Pi's boot card** - the device only recognizes a card within ~10% of the boot
card's size. It can be slightly smaller as long as the system data fits.

**Steps:**

1. With the Library **powered off**, insert the blank/target microSD card (via a USB
   reader).
2. Power the Pi on. Early in startup it detects the extra card and begins cloning - the
   display walks through a series of progress screens (checking, partitioning, formatting,
   copying, finalizing). Services do **not** start during a clone.
3. When it finishes, the screen shows a **success** message and asks you to **remove the
   cloned card**. Pull the card out.
4. The Pi then reboots on its own and starts normally as the Library.

If something goes wrong, the screen shows a **failure** message and the Pi shuts down -
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
tell it to stay connected anyway - that's expected for an offline device.

**Can several people use it at once?**
Yes. Many devices can connect and browse at the same time.

**Does it track me or use cookies?**
No. The Library doesn't track you, doesn't use cookies, and doesn't phone home. Your
library is yours - a straightforward experience, just like the internet used to be.

**A page says a service "failed to start" or content is "missing."**
That's a message for whoever set up the device - the content for that service needs to be
added. See [DEVELOPERS.md](DEVELOPERS.md).

** Are there any easter eggs?**
If you have a tft screen that is touch tap on it in the right sequence or find it in the code
