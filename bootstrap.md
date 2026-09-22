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
| Fresh Install | Choose a display, review the settings and start First Boot |
| Reinstall | Confirm removal of progress flags, staged files and all Podman images, then return to the menu |
| Resume Install | Use stage flags to select the next pending stage |
| System Status | Show stage flags, uptime and whether Ansible is running |
| Advanced Options | Run a stage manually, reset flags or view the installation log |

**USB storage may be erased during First Boot.** The installer prepares a detected
USB content disk as exFAT with the label `Library_USB` when that label is absent.
It displays a countdown before formatting. Disconnect unrelated storage first;
a correctly labelled content drive is retained.

Reinstall removes `/root/install`, `/root/display`, `/root/start_library`, the
stage flags and all Podman images. It is not a routine service update. First Boot
can subsequently format storage as described above.

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
`/root/bootstrap` interactively and choose Resume Install or the appropriate
Advanced Options stage.

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
choosing the stage to retry. Resetting flags alone does not undo installed files.

## Troubleshooting

- **No automatic resume:** check `sudo crontab -l`, the five-minute window and
  `/root/install.log`. Launch `/root/bootstrap` manually if needed.
- **Container build failed:** check the failing image in the build output. Keep
  both radio contexts in the checkout and ensure package and release downloads
  are reachable. See the [build pipeline](docs/DEVELOPERS.md#container-build-pipeline).
- **Ansible failed:** inspect `/root/installplay.log` and the recap. Use Advanced
  Options to retry the affected stage after fixing the underlying problem.
- **Radio setup appears instead of messaging:** a USB port alone does not prove
  Meshtastic is running. Check the radio firmware, selected device and serial-port
  ownership using the [Meshtastic guide](setup_library/files/containers/meshtastic/README.md).
