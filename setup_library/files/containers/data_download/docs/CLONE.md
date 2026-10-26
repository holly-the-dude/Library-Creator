# Clone the SD card or Library_USB

Open **Downloads → Clone**. Choose **SD card (bootable system)** or
**Library_USB (content drive)**. Insert the destination into the **Pi**:
an SD card in a USB SD adapter, or a USB stick. Select **Scan for destination**,
check the device/model/serial/capacity, and choose **Erase and clone…**.
Type the displayed destination device name to confirm erasing **all its data**.
Scanning does not change any drive. Selections expire after five minutes;
a new scan invalidates earlier selections.

The source drive's full capacity does not determine the minimum. A 512 GB
Library_USB containing about 100 GB of data can be copied to a 128 GB stick.
The scan reports used bytes and required capacity, including filesystem
headroom. USB uses used bytes + 5% (at least 256 MiB) + partition alignment;
SD uses used root bytes + 10% (at least 512 MiB), a boot partition large enough
for its files, and alignment. This is a conservative estimate, not a guarantee
against source growth or different allocation sizes. Exactly 100 GB of media
is insufficient for 100 GB of files plus filesystem metadata.

Only unused, writable USB disks are offered. Mounted partitions, swap,
active device-mapper/RAID holders, the running system disk, boot disk, and
mounted Library disk are excluded. Device identity, including the kernel's
insertion sequence, and available capacity are rechecked when starting and
again immediately before partitioning. Unmount an otherwise eligible spare
drive on the Pi before scanning; the app does not automatically unmount it.

Finish uploads, queued downloads, extraction, and catalog refresh first.
During cloning, the downloader blocks new writes, refresh, routing changes,
and its Restart button. Other running Podman containers stop and restart
afterward, except the downloader and hotspot (which keep the browser connected).
The Library readers will be temporarily unavailable. Avoid manual changes,
other power controls, container restarts, or unplugging either drive during a
clone. You may close/reopen the browser; the host continues copying.

The yellow-orange progress bar counts containers as they stop and restart.
While copying, it highlights bytes copied and an estimated percentage based on
used space for that filesystem: USB content, SD root, or SD boot. SD progress
resets for the boot-files stage. Used space includes filesystem metadata and
allocation overhead, so this estimate can differ from the final copied bytes.
Formatting and final writes show an indeterminate bar; the page reports the
clone complete only after cleanup and reader restart succeed.
On success, the destination
has been synced and unmounted. **Remove the clone before restarting**: the USB
copy deliberately has the same `Library_USB` label. Failed copies must not be
used as finished clones. If cleanup failed or power was lost, check mounts and
host logs before removal and restart any readers that remained stopped.

## Supported layouts

- **SD:** the standard Pi `/dev/mmcblk0` layout with two partitions: FAT at
  `/boot/firmware` and ext4 at `/`. File-level rsync preserves root ownership,
  permissions, hard links, ACLs and xattrs. The new FAT/ext4 partitions fill the
  destination as appropriate; fresh UUIDs/PARTUUIDs are written to the copy's
  `fstab` and `cmdline.txt`. The separate `/Library` content drive is excluded.
  Destination sectors must be 512 bytes, with disk capacity below 2 TiB.
- **Library_USB:** the exFAT filesystem mounted at `/Library` and labelled
  `Library_USB`. A new GPT/exFAT partition fills the destination and receives
  the files and directories, including hidden files. It is labelled
  `Library_USB` for the existing startup playbook.

This is a live file-level copy, not an atomic system snapshot. Containers are
stopped to reduce changes, but host services remain running; copy errors are
reported as failures. Test a cloned SD card by booting it on the target Pi.
The existing startup-time cloning block in `start_library.yml` is unchanged.

## Installation

New installations install the host helper, packages, and socket through
bootstrap's Second Boot (`setup_library/01_install_ansible.yml`).

For an existing Pi with the updated downloader image installed, run the updated
`bootstrap` and select **5) Install / Repair Clone**, or run:

```sh
sudo bash /root/Library-Creator/bootstrap --install-clone
```

Adjust the path to your updated source folder. This installs the host support,
updates the startup playbook, and recreates the downloader with the socket mount.
Finish transfers, source refresh, and cloning first; keep `/Library` mounted.
The page briefly disconnects during recreation. Refresh it afterward.

For manual installation instead, run these commands
as root **from this repository's root**:

```sh
apt-get install python3 rsync util-linux fdisk udev dosfstools e2fsprogs exfatprogs
install -m 0755 setup_library/files/containers/data_download/clone_host.py /usr/local/bin/library_clone.py
install -m 0644 setup_library/files/library-clone.socket setup_library/files/library-clone.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now library-clone.socket
```

If updating an already running `library-clone.service`, finish any clone first,
then restart that service to load the new helper. Never restart it mid-copy.

Deploy the updated `start_library.yml` to `/root/start_library.yml`, rebuild the
`data_download` image, and recreate the downloader container. The startup
playbook binds `/run/library-clone` read-only when its socket exists. The existing
restart socket/service is independent and unchanged. A missing clone service
leaves the Clone menu visible with installation guidance and disabled controls.

For standalone rootful Podman, add this mount after installing the host service:

```text
--mount type=bind,src=/run/library-clone,dst=/run/library-clone,ro=true
```

For Compose, from the downloader directory:

```sh
sudo podman compose -f compose.yaml -f compose.clone.yaml up -d --build
```

The optional override requires the socket directory to exist. Default Compose
still runs without the host cloning service. The downloader remains unprivileged
and has no block-device access or Podman socket. The host helper runs as root
and performs only fixed clone actions; it accepts no shell commands from clients.
The web app uses its existing request-token protection, not a login: anyone
with access to the trusted Library LAN can operate it, including erasing an
eligible spare drive after confirmation.

## API and testing

`GET /api/state` includes `clone.available`, `clone.status`, `clone.message`,
and, while working, the source, destination, `phase`, and `copied` byte count.
Copy phases include `copy_total` (estimated used bytes for that filesystem).
Stopping/restarting phases include `containers_done` and `containers_total`.
`POST /api/clone/scan` takes `{"source":"sd"}` or `{"source":"usb"}` and returns
source used/required bytes and eligible targets with `fits` and a one-use token.
`POST /api/clone/start` takes the token and a `confirmation` matching the displayed
device name. Both require the usual `X-Library-Token` header. Starting returns
immediately; poll state for the result. There is no cancel action once erasure
starts. A failed copy is not silently retried.

The root-only Unix socket `/run/library-clone/clone.sock` accepts bounded JSON
lines with `status`, `scan`, or `start` actions. It returns
`{"ok":true,"result":...}` or `{"ok":false,"error":"..."}`. State is saved in
`/run/library-clone/status.json`, allowing a restarted helper to report a copy
interrupted during this boot.

Run the downloader Python suite and JavaScript UI tests. Hardware commands in
clone tests are mocked; they never format a real disk. Pi acceptance testing:
verify protected/mounted disks are absent, reject an undersized destination,
clone 100 GB from a larger USB to a 128 GB stick, compare files, safely remove
it, and test it on the Pi. Repeat with a smaller SD destination, verify it boots
with its separate Library_USB, and check a failed copy restores stopped readers.

```sh
journalctl -u library-clone.service -b
systemctl status library-clone.socket
```
