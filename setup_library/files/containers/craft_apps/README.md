# Library Office

WordCraft, DeckCraft, and GridCraft run as native Linux apps in one desktop
streamed to your browser. This optional add-on requires **a keyboard and a pointing
device: mouse, touchscreen, or trackpad** on the device running the browser.
No client app needs installing. It works offline after the image has been built.

Open **Office** on the Library homepage or **https://library:3001**
(**https://10.1.1.1:3001** over Library WiFi). The Selkies viewer includes desktop
audio and uses a self-signed certificate, so the browser may show a certificate
warning. Office is HTTPS only; port 3000 is not published on the appliance.

Save into **/documents** in the app's file dialog. That directory is the host's
**/Library/documents**, shared by all three apps. The desktop's Documents shortcut
also points there. Home, File System, Trash, and removable-drive desktop icons
are hidden. App launchers start in `/documents`, and use it as their home folder
for new file dialogs while retaining settings in `/config`. Apps may remember
the location of an existing document or a previously selected folder. Files persist when the container is replaced. Settings and
desktop preferences live separately in the `craft-apps-config` Podman volume on
the system disk. This supports exFAT content drives, which cannot store the
symlinks and Unix permissions used by a Linux desktop.

## Build and start

Run on the Library appliance from this directory:

```bash
sudo podman build --format docker -t localhost/craft_apps:latest -f Containerfile .
sudo bash start.sh
```

`start.sh` creates the documents directory if missing and matches the desktop
UID/GID to its owner, preserving existing ownership and document contents. On the
Library's root-owned exFAT drive this means UID/GID 0 inside the container. You can
override this with `PUID` and `PGID` when another user has write permission.
`CRAFT_DOCUMENTS`, `CRAFT_CONFIG`, and `CRAFT_PORT` (3001)
override the host paths and published HTTPS port for a standalone installation. `CRAFT_CONFIG` accepts a
Podman volume name or a directory on a filesystem with Unix permissions. The container path remains
`/documents`. Restarting replaces the container, so save open work first.

The Compose file is an alternative for an existing Podman `podman` bridge. Create
the documents directory first when using Compose directly; set PUID/PGID to its
owner if it is not root.

## Bootstrap opt-in and startup

Fresh Install and Restart Install ask **Enable the Office add-on? [y/yes/N]**
after the display choice and explain the input-device requirement. The default
is No. The build retains the image for later offline use either way:

| Choice / tags | Startup behavior |
| --- | --- |
| Yes: `localhost/craft_apps:latest` | Start Office and create `/Library/documents` if missing |
| No: `localhost/craft_apps:dontrun` | Stop any existing Office container and skip startup |
| Both tags | `:dontrun` wins; Office stays disabled |
| Neither tag | Skip Office |

To change the choice on an existing Library, use **6) Configure Office** in
bootstrap or `sudo bash /path/to/checkout/bootstrap --configure-office`. Save
open documents before applying the change. This uses the installed image; it
does not run a full reinstall. Restart the Library afterward to apply startup
and regenerate the homepage. The updated startup playbook and webserver image
must already be deployed on an older appliance.

For manual changes from this directory:

```bash
sudo bash set-enabled.sh no   # Retag as :dontrun, remove :latest, stop Office
sudo bash set-enabled.sh yes  # Restore :latest and remove :dontrun
sudo bash start.sh            # Start enabled Office only (replaces its container)
```

Disabling retains documents and the settings volume. The helper changes image
aliases without deleting images. `build_pods.sh` preserves an existing disabled
choice unless bootstrap supplies a new `LIBRARY_OFFICE=yes|no` answer. After a
manual image build/load, an existing `:dontrun` tag still blocks startup; use the
helper to enable it explicitly. Compose is a manual launch alternative and does
not apply the bootstrap tag checks; use `start.sh` for those checks.

`create_tar_pods.sh` exports `craft_apps.tar` using the enabled or disabled tag.
Load it on another appliance with `sudo podman load -i craft_apps.tar`.
The startup playbook uses bridge address `10.88.0.218`, publishes only HTTPS
port 3001, and accepts `craft_puid`/`craft_pgid` ownership overrides. To run only
its Office tasks after saving open work:

```bash
sudo /root/.local/bin/ansible-playbook /root/start_library.yml --tags craft_apps -i localhost, -c local
```

The webserver probes the internal Selkies service and shows **Office** only when
it responds during page generation. Its link always uses HTTPS and keeps the
hostname used to open the Library. After manually stopping or starting Office,
regenerate pages with `podman exec <webserver-container> python3 /root/library.py`
or restart the Library. The navigation is generated at startup, not polled live.

Internet access is needed to build the image, not to use the installed apps.
The image pins WordCraft 0.13.2, DeckCraft 0.13.1, and GridCraft 0.14.2 and verifies
their packages against checked-in upstream SHA-256 checksums. Builds support
ARM64 and x86-64; build on the same architecture as the destination. To upgrade,
update the versions in `install-apps.sh` and their hashes in `packages.sha256`,
then rebuild and restart after saving open documents.

This is one shared desktop session, not separate accounts for each browser user.
It is configured for the Library's trusted local network, without a login.

## Troubleshooting

```bash
sudo podman logs craft_apps
sudo podman exec craft_apps s6-setuidgid abc test -w /documents
```

Use **https** on port 3001. For file permissions, match the desktop UID/GID to
the shared folder; avoid recursively changing existing document owners.
On SELinux hosts, apply suitable container labels to dedicated bind directories
(shared documents need `:z`, private settings `:Z`); the appliance normally uses
Debian without SELinux. A GPU is optional; the default uses software rendering.

Upstream: [Webtop](https://docs.linuxserver.io/images/docker-webtop/),
[WordCraft](https://github.com/storytold/wordcraft),
[DeckCraft](https://github.com/storytold/deckcraft),
[GridCraft](https://github.com/storytold/gridcraft).
