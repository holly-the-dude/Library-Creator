# Bootstrap installer reference

[`bootstrap`](bootstrap) is the menu-driven Raspberry Pi installer. For hardware,
OS preparation and content downloads, follow the [installation guide](docs/INSTALL.md).
For the container architecture and runtime playbook, see the
[developer guide](docs/DEVELOPERS.md).

## Start the installer

Use a root shell on the Pi. The installer expects the repository at
`/root/Library-Creator`:

```bash
cd /root
git clone https://github.com/holly-the-dude/Library-Creator.git
cd Library-Creator
./bootstrap
```

For testing, you can also copy or extract the project without its `.git` folder.
Keep `bootstrap` and the complete `setup_library` directory together, run
`./bootstrap` from that copy, and choose **Fresh Install** or **Restart Install**.
The source folder can have any name. **Reinstall / Upgrade** still requires a Git
checkout because it updates the source with `git pull`.

First Boot copies the checkout into `/root/install` and the script into
`/root/bootstrap`. The current installer uses this checkout; it does not download
an encrypted `install.zip` or ask for an archive password during Fresh Install.
Internet access is required for packages, image builds and firmware downloads.
The finished services use their locally installed assets.

Use a 64-bit Raspberry Pi OS installation, root access, a reliable power supply
and a USB content drive. Display options are TFT 3.5-inch, TFT 2.4-inch, HDMI
status messages, or HDMI desktop with a kiosk browser. HDMI can use the monitor's
native resolution or an explicitly selected resolution.

## Menus

| Option | Action |
| --- | --- |
| Fresh Install | Choose a display, review the settings, clear stage flags and start First Boot |
| Reinstall / Upgrade | Confirm, run `git pull --ff-only` in `/root/Library-Creator`, then perform reinstall cleanup and exit |
| Restart Install | Clear stage flags and run the same fresh installation from First Boot |
| System Status | Show stage flags, uptime and whether Ansible is running |
| Install / Repair Clone | Install the host clone service and recreate the downloader with its socket mount |

**USB storage may be erased during First Boot.** The installer prepares a detected
USB content disk as exFAT with the label `Library_USB` when that label is absent.
It displays a countdown before formatting. Disconnect unrelated storage first;
a correctly labelled content drive is retained.

**2) Reinstall / Upgrade** first updates `/root/Library-Creator` from the current
branch's configured upstream with `git pull --ff-only`. It uses that checkout
regardless of your working directory or whether you launched `/root/bootstrap`.
Internet access to the Git remote is required. A missing checkout or failed pull
stops the operation before cleanup; Git errors are shown so you can resolve them
and retry. The installer does not force a reset, discard local edits, or create
a merge commit when branches have diverged.

After a successful pull, it performs the same reinstall cleanup: remove
`/root/install`, `/root/display`, `/root/start_library` and the stage flags,
stop all Podman containers, then remove all Podman images. It exits afterward.
Run `/root/Library-Creator/bootstrap` again and choose **1) Fresh Install** to
install the updated checkout, including any changes to bootstrap itself.

This is a full reinstall, not a routine service update. The cleanup does not
delete USB content, but First Boot can subsequently format storage as described
above.

## Enable Clone on an existing Library

Use the updated source folder on the Pi and choose **5) Install / Repair Clone**,
or run the same targeted setup directly:

```bash
sudo bash /root/Library-Creator/bootstrap --install-clone
```

The source folder may have another name; bootstrap resolves the folder you
launched. This uses the already installed `localhost/data_download:latest`
image, which must include the Clone interface. Build/load that updated image
first if needed. Keep `Library_USB` mounted at `/Library` and finish transfers,
source refresh and cloning before starting. Package installation needs internet.

Bootstrap installs the dependencies and host helper through the `clone_service`
Ansible tasks, enables the socket, reloads an idle running helper, installs the
updated `/root/start_library.yml`, and recreates the downloader using only the
`data_download` tasks. It checks that the socket is visible inside the container.
The page will briefly disconnect; refresh it and select **Clone** afterward.
This option does not run the full reinstall cleanup, change boot-stage flags,
or reboot. Fresh installs include the host service in Second Boot automatically.

See [Clone setup and usage](setup_library/files/containers/data_download/docs/CLONE.md)
for supported drives and manual installation commands.

## Boot stages

### First Boot

1. Prepare and mount the USB content storage, including its base content layout.
2. Install system packages and copy the checkout into `/root/install`.
3. Run `reconstitute.sh`, `update_rasbase.sh`, then `build_pods.sh` from
   `setup_library/files/containers` to load the old base, update it and build services.
4. Configure the selected TFT or HDMI display and install remaining utilities.
5. Configure networking and schedule `/root/bootstrap --auto`, then reboot.

The build includes both `localhost/meshtastic:latest` and
`localhost/meshflash:latest`. The build script requires both radio Containerfiles.
Meshflash downloads its ESP32 firmware snapshot during this build so firmware
setup later works offline. Installing the Library does not flash a connected radio.

Container discovery also builds `street_zim`, `music_player`, and `data_download`
from their folders. Podman builds use `--format docker` to preserve image health
checks; Docker itself is not required. At normal startup, installed StreetZim
and iPod-style player images start even with empty content folders. The hub's
**Maps** and **Music** menus offer both viewers and both players respectively.
StreetZim supplies shared USB GPS when healthy; see the
[runtime GPS behavior](docs/DEVELOPERS.md#maps-gps-internals) and
[deployment steps](docs/DEVELOPERS.md#deploying-the-updated-menus-and-containers).

### Second Boot

Show a configuration splash, wait for services to settle and run
`/root/install/setup_library/01_install_ansible.yml`. Output is saved to
`/root/installplay.log`. The script uses the presence of
`/etc/systemd/system/shutdown_library.service` as its completion check, then reboots.
Inspect the Ansible recap as well when diagnosing a partial installation.

### Third Boot

Remove the installer cron entry, show the read-only notice, remove the temporary
`preconfigured.nmconnection` network profile and reboot into normal startup.

Normal service startup is handled by `/root/start_library.yml`, not by the
installer's stage flags. Its radio check selects the Meshtastic web client or
meshflash setup at `http://library:8086`. After firmware setup finishes, reboot
or rerun the [radio startup check](docs/INSTALL.md#set-up-the-meshtastic-radio).

## Automatic resume and files

The installer writes this root cron entry:

```cron
* * * * * /root/bootstrap --auto 2>&1 | /usr/bin/tee -a /root/install.log
```

Auto mode runs within the first five minutes after boot and skips work if
`ansible-playbook` is already running. Outside that window, use
`/root/bootstrap` interactively and choose Restart Install to begin again.

Fresh Install and Restart Install both remove `/root/.0boot`, `/root/.firstboot`,
`/root/.secondboot` and `/root/.thirdboot` after the OS preflight succeeds, then
rerun First Boot with your selected display. Restart Install does not continue
from the previous stage. Later stages still run automatically after reboot.

| Path | Purpose |
| --- | --- |
| `/root/Library-Creator/` | Original repository checkout |
| `/root/install/` | Staged installation files copied from the checkout |
| `/root/bootstrap` | Installer used after reboot |
| `/root/.0boot` | Installer boot-mode marker |
| `/root/.firstboot`, `.secondboot`, `.thirdboot` | Stage selection markers |
| `/root/install.log` | Output from automatic resume |
| `/root/installplay.log` | Ansible installation output |
| `/root/start_library.yml` | Deployed runtime startup playbook |
| `/Library/` | Mounted content storage and persistent service data |

Stage flags are not a complete success record: First Boot and Third Boot create
their flags before finishing their work. After a failure, inspect the logs before
choosing Restart Install. Resetting flags alone does not undo installed files.

## Troubleshooting

- **No automatic resume:** check `sudo crontab -l`, the five-minute window and
  `/root/install.log`. Launch `/root/bootstrap` manually if needed.
- **Container build failed:** check the failing image in the build output. Keep
  both radio contexts in the checkout and ensure package and release downloads
  are reachable. See the [build pipeline](docs/DEVELOPERS.md#container-build-pipeline).
- **Ansible failed:** inspect `/root/installplay.log` and the recap. Choose
  Restart Install after fixing the underlying problem.
- **Radio setup appears instead of messaging:** a USB port alone does not prove
  Meshtastic is running. Check the radio firmware, selected device and serial-port
  ownership using the [Meshtastic guide](setup_library/files/containers/meshtastic/README.md).
