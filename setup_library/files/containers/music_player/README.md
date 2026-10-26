# Library Music player

Library Music plays full audio files from a server-side music folder and its
subfolders. It works offline without an account or external asset requests. The click wheel, playback controls, shuffle,
repeat, volume, and seeking remain available. The default appearance is a purple
and gold player; the original silver Classic skin is also available.

## Run directly

Python 3.10 or newer is the only requirement; no packages need installing.

```bash
cd /home/theman/github/Library-Creator/setup_library/files/containers/music_player
python3 server.py --music-dir /Library/music --port 2001
```

Open <http://localhost:2001> or <http://localhost:2001/music.html>. Substitute your actual music directory, quoting it
if it contains spaces. To listen on your LAN, add `--host 0.0.0.0` and open
`http://YOUR-SERVER-IP:2001` on another device. This is a trusted-LAN server with
no authentication; anyone who can reach its port can read the music library.
Opening the HTML directly with `file://` cannot access a server-side folder.

## Run with Podman

This follows Library-Creator's `Containerfile` and read-only `/music` mount
pattern. It builds from your Library image using `FROM ${BASE_IMAGE}` with
`localhost/rasbase_master:latest` as the default, and installs Python 3 from
the base's Debian repositories. Override with `--build-arg BASE_IMAGE=...`.
It runs separately from LMS at **10.88.0.217**, using port **2001**, while LMS
continues using its existing port 9099 and `/music` homepage link.

```bash
cd /home/theman/github/Library-Creator/setup_library/files/containers/music_player
sudo podman build --format docker -t localhost/music_player:latest -f Containerfile .
sudo podman run -d --name music_player --restart unless-stopped \
  --network podman --ip 10.88.0.217 --read-only -p 2001:8080 \
  -v /Library/music:/music:ro \
  localhost/music_player:latest
```

The container runs as UID/GID 1000. Music files must be readable and their
directories traversable by that user. Use `--user UID:GID` if your library uses
a different owner. SELinux hosts may need `:ro,z` for a shared music mount.
Build the Library base image first. Package installation needs internet during
the build; playback runs offline. Use rootful Podman on the Library appliance,
matching the other services.

Podman Compose is also supported if the Compose provider is installed:

```bash
sudo podman compose up -d --build
```

`MUSIC_PATH` is the host directory. Inside the container, `MUSIC_DIR` defaults
to `/music`. The server also accepts `HOST` and `PORT` environment variables.
No database, writable music mount, or persistent application volume is needed.

Library-Creator's `build_pods.sh` discovers this `music_player` directory and
builds `localhost/music_player:latest`, matching Compose. The updated
`start_library.yml` starts it automatically when the image is installed, even
with an empty music folder. It mounts `/Library/music` read-only and needs no
LMS database. The homepage's **Music** menu offers **Music library (LMS)** and
**iPod-style player**; unavailable players are labelled **Not running**.

Compose uses the existing `podman` bridge and the same fixed address. Override
`MUSIC_PATH`, `MUSIC_PORT`, `MUSIC_IP`, `MUSIC_NETWORK`, or `BASE_IMAGE` with
`sudo env NAME=value podman compose ...` if needed. The homepage configuration
must match any custom IP or port.

To install the integration, rebuild `music_player` and `webserver` from their
respective folders, using `sudo podman build --format docker -t
localhost/NAME:latest -f Containerfile .`. Install the updated
`setup_library/files/start_library.yml` as `/root/start_library.yml` on the
appliance, then restart the Library normally. Existing running containers do
not acquire new images just by rebuilding. Open **Music → iPod-style player**
or `http://10.1.1.1:2001` on the hotspot. Both players read the same music files.

The Compose service is `music_player` and its port override is `MUSIC_PORT`
(default 2001). After upgrading from a previous container name, stop the old
container before starting this one so the port is free. Rebuild and recreate
the container to apply these changes.

## Browse and play

- **Folders** follows the directory tree. Select a subfolder to enter it and a
  song to play the songs directly in that folder. MENU returns to the parent.
- **Songs** includes every audio file found recursively. Select a song to start
  playback from there; shuffle and repeat are under Settings.
- **Artists** groups by the first folder beneath the music root. For example,
  `Artist/Album/01 - Title.mp3` displays `Artist`, `Album`, and `01 - Title`.
  Root-level files use “Unknown Artist.” Embedded tags and cover art are not
  read in this version.
- **Rescan music folder** scans the configured folder and its subfolders again
  without reloading the player or stopping playback. The button shows scanning
  progress, then a completion count or an error. Failed scans keep the previous
  library available; press the button again to retry. Nothing is uploaded or modified.
- Arrow keys navigate the wheel; Enter selects, Escape goes back, and Space
  toggles playback. On Now Playing, the wheel adjusts volume; the center button
  switches to seeking.

Recognized extensions: MP3, M4A, MP4, AAC, FLAC, OGG, OGA, Opus, WAV, and WebM.
Playback depends on the browser's codec support; the server does not transcode
or decrypt DRM-protected audio. Unsupported or missing tracks show an error
below the player so you can skip them. Files are streamed with byte-range
support for seeking, rather than loading a whole song into server memory.

Hidden files/directories and playlist files are ignored. Directory symlinks
are not followed, and symlinked files outside the music root are excluded.

## Skins and saved settings

Open **Settings**, scroll to **Skin**, and press the center button or Enter to
switch between **Purple** and **Classic**. The change applies immediately without
reloading the page or interrupting a song. Purple is the default on first use,
when older saved preferences have no skin field, and after **Reset All Settings**.
An explicit Classic choice stays selected when the page is reloaded.

The purple case, gold trim and controls, and cream LCD follow the supplied
reference image. CSS renders the skin; the PNG and its absolute path
are not runtime dependencies. Classic retains the original silver case, gray
wheel, and backlight styling. Both skins use the existing wheel/keyboard controls
and backlight settings.

Preferences are stored in the browser's `localStorage` under
`library-music:settings`. Existing preferences migrate automatically from the
legacy storage key when visiting the same site origin. They belong to that browser and site origin, not the USB
music drive. Unknown skin values fall back to Purple. If storage is unavailable,
the player still works but preferences may not survive a reload.

## Code guide: music.html

The HTML is self-contained: it embeds the font, wheel texture, Svelte runtime,
and compiled components. There is no frontend build step or original `.svelte`
source tree in this directory. The page-level shell shows scan/playback errors;
`<library-music-player>` renders the player inside an open Shadow DOM.

An inline maintenance map at the top and comments at the customization points
explain the important data flows. Generated short identifiers, numeric `ctx[]`
slots, and update masks are coupled; avoid renaming them or editing indexes
independently. Keep new customization logic readable and outside generated DOM
fragments when possible.

| Area | Symbols / responsibility |
| --- | --- |
| Appearance | `PLAYER_SKINS` defines valid stored values; `PLAYER_SKIN_STYLES` holds scoped purple CSS. Classic uses the original CSS. |
| Settings | `Pe` defines defaults; `Ds` validates/migrates each field; `_s` reads storage; `Cs` writes it; `ie` is the reactive store; `Hs` resets preferences. |
| Menus | `xh` builds Settings rows; `ol` creates inline toggles; `gn` defines screens; `Yl` maps stored values to readable labels. Select cycles the row's allowed values through the shared store. |
| Local folders | `localFolderItems` builds folder/song rows; `nn` resolves a folder or artist into its playable song queue. Server-assigned IDs identify content. |
| Library loading | `yr` fetches relative `api/library` without caching and validates schema version 3; `gr` serializes scans and preserves ready data during refresh/error; `bindLibraryControls` connects the button and status display to that store. |
| Audio | `Ir` owns an audio element and gain node; `Sr` manages the queue, crossfades, shuffle, and repeat; `Tr` connects playback state to the UI. The historical `previewUrl` field carries a full local song URL. |
| Input and lifecycle | `i1` connects wheel and keyboard input to navigation/playback and manages timers. `a1` registers the skin-store subscription while connected and removes it on disconnect. |

To add another skin: add its ID to `PLAYER_SKINS`, add a value translation and
`lo` label mapping, and add host-scoped CSS. The settings row automatically uses
the enum values. Set `Pe.skin` if changing the default. The host's `data-skin`
attribute selects the CSS; switching it does not remount the audio component.
The purple selectors include `.music-player` to outrank generated style rules and OS
dark-mode overrides. Keep focus indicators and LCD/backlight contrast readable.

Changes to the HTML apply after a page reload when running `server.py` directly.
For a container installation, rebuild the image and recreate the container first.

## Checks

```bash
python3 -m unittest discover -s tests -v
node tests/frontend.test.cjs
```

The frontend checks cover folder navigation, library loading, skin defaults,
migration of older settings, persistence of Classic, resetting to Purple, and
invalid/unavailable storage. Rescan checks cover new tracks, visible busy/result
states, duplicate requests, initial failure recovery, and preservation of the
previous catalog on errors. For a browser check, open Settings → Skin, switch
both ways during playback, reload to confirm persistence, and reset settings.
Check both narrow screens and OS light/dark appearance; the purple backlight
should remain visibly different when switched on and off.

### Rescan troubleshooting

Serve the page through `server.py` or the container; opening the HTML as a
`file://` document cannot scan the server's music folder. A rescan reads the
configured `--music-dir` / `MUSIC_DIR` directory, or the `/music` bind mount in
the container. It does not select a folder on the browser's device.

The decorative reflection below the music player has `pointer-events: none` in both
skins so it cannot cover the Rescan button's click area. The button's handler
is registered with the mounted player and removed on disconnect. Scanning
replaces the browse catalog, while the current playback queue remains in place;
select a song from the updated catalog to start a new queue. Files removed from
disk may no longer play even if they remain in an older queue.
