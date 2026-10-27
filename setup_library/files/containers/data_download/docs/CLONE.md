# Clone the SD card or Library_USB

Open **Downloads → Clone**. Choose **SD card (bootable system)** or
**Library_USB (content drive)**. Insert the destination into the **Pi**:
an SD card in a USB SD reader for the operating system, or a USB
stick for Library_USB content. Select **Scan for destination**,
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
After formatting, the helper also checks the actual destination filesystem's
available space before copying each filesystem. SD root copies preserve sparse
files, so unallocated zero-filled regions need not expand into allocated blocks.

Only unused, writable USB disks (or native SD cards for OS cloning) are scanned. Mounted partitions, swap,
active device-mapper/RAID holders, the running system disk, boot disk, and
mounted Library disk are excluded. Device identity, including the kernel's
insertion sequence, media type, and available capacity are rechecked when starting and
again immediately before partitioning. Unmount an otherwise eligible spare
drive on the Pi before scanning; the app does not automatically unmount it.

**Operating-system clones require an SD card.** The scan labels detected SD
cards and blocks identified USB sticks or other media. If a reader cannot
identify its inserted media, the destination is available with a warning.
Before the erase confirmation, a separate prompt asks you to verify both that
this destination is an **SD card in a reader, not a USB stick**, and that you
intend to copy the **Library operating system**. Cancel either prompt to stop.
The usual typed destination-device confirmation is still required afterward.
Library_USB content cloning continues to allow USB sticks without this extra
OS-copy prompt.

Native MMC-subsystem cards must report card type `SD`. USB readers can expose
an inserted-media property of `ID_DRIVE_MEDIA_FLASH_SD`, `_SDHC`, or `_SDXC`.
These are distinct from reader capabilities such as `ID_DRIVE_FLASH_SD`; see
[UDisks media classifications](https://github.com/storaged-project/udisks/blob/master/src/udiskslinuxdrive.c).
Model names containing “SD” or “Card Reader”, USB connection, and removable-drive
flags are not accepted as proof of SD media. Generic readers without media
identification require your physical verification instead.

The host requires explicit verification for unknown media, bound to the selected
scan token. It repeats identity, media, mount and capacity checks before erasure.
Verification does not bypass these checks or allow a device identified as
non-SD media. If previously identified SD media becomes unknown, scan again to
get the verification prompt. These checks apply to the downloader Clone flow;
the existing startup-time cloning block remains unchanged.

Finish uploads, queued downloads, and extraction first. Background catalog
discovery does not delay the **Erase and clone** button: it only reads network
metadata and updates memory. Its disk-cache write is skipped if a clone is
running or the host clone status is unknown. Disabled clone buttons show what
they are waiting for, such as active transfers or the host service.
During cloning, the downloader blocks new writes, refresh, routing changes,
and its Restart button. Other running Podman containers stop for the copy,
except the downloader and hotspot (which keep the browser connected).
The Library readers will be temporarily unavailable. Avoid manual changes,
other power controls, container restarts, or unplugging either drive during a
clone. You may close/reopen the browser; the host continues copying.

The yellow-orange progress bar counts containers as they stop.
While copying, it highlights bytes copied and an estimated percentage based on
used space for that filesystem: USB content, SD root, or SD boot. SD progress
resets for the boot-files stage. Used space includes filesystem metadata and
allocation overhead, so this estimate can differ from the final copied bytes.
Formatting and final writes show an indeterminate bar. After the copy is synced
and the destination is successfully unmounted, the page shows **Copy complete**,
100%, and a message that the destination is safely ejected.

**Unplug only the destination when prompted. Leave the original drive connected.**
The host waits for destination removal, then automatically restarts the Library.
Keep power connected and reload the page when the Library is back online.
Readers start during normal boot; the clone helper does not restart individual
containers after a successful copy. This applies to both USB and SD clones.
Unmounting alone does not prevent the copied `Library_USB` label from being
detected on the next boot, so physical removal is required before the reboot.

A failed copy or unmount never triggers an automatic reboot. The helper attempts
to restore stopped readers and reports the failure. Failed copies must not be
used as finished clones. If cleanup failed or power was lost, check mounts and
host logs before removal. If copying and unmounting succeeded but the reboot
request failed, the page asks for a manual restart and keeps new writes blocked.
Remove the destination first, then SSH into the Pi and run `sudo systemctl reboot`.
The same manual recovery applies if the clone helper is restarted while waiting
for removal. The normal Library restart helper is not used for this completion
flow, because it issues additional Podman commands.

## Supported layouts

- **SD:** the standard Pi `/dev/mmcblk0` layout with two partitions: FAT at
  `/boot/firmware` and ext4 at `/`. File-level rsync preserves root ownership,
  permissions, hard links, sparse files, ACLs and xattrs. The new FAT/ext4 partitions fill the
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

## Troubleshooting a full destination

If rsync reports **No space left on device**, the clone is incomplete. The
filename identifies the stage: `/mnt/library-clone-.../boot/initrd.img-...`
belongs to the destination **root** filesystem; files under its
`boot/firmware/` directory are copied to the separate FAT boot partition.
Increasing only the boot partition does not fix a full root filesystem.

Earlier helper versions left the root partition's starting offset unspecified.
This could create a **7 MiB root partition before the boot partition**, leaving
most of the card unused. If `lsblk` shows that layout, update the helper and run
a new clone. The corrected layout explicitly starts root after boot and uses
the remaining card space. A failed copy cannot be repaired just by enlarging
its partition: the missing files still need to be copied.

The scan estimates capacity from allocated source space. The helper preserves
sparse files during the root copy and checks available space after formatting,
but source growth, inode limits, filesystem differences, or storage problems can
still cause a failure. Copy errors include destination free bytes and free inodes
when available. Podman errors that follow describe attempts to restore readers;
they do not replace the original copy error.

On the Pi, collect the layout, source usage, and clone service log:

```sh
lsblk -b -o NAME,SIZE,FSTYPE,MOUNTPOINTS
df -h / /boot/firmware
df -i / /boot/firmware
journalctl -u library-clone.service -b
```

Keep the failed destination out of normal boot use. Before removing it, confirm
that none of its partitions remain mounted. Update the host helper before
retrying; a larger destination may be needed if the new capacity check rejects it.

## API and testing

`GET /api/state` includes `clone.available`, `clone.status`, `clone.message`,
and, while working, the source, destination, `phase`, and `copied` byte count.
Copy phases include `copy_total` (estimated used bytes for that filesystem).
Stopping and failure-recovery restarting phases include `containers_done` and
`containers_total`. Successful copying and unmounting set `copy_complete: true`.
The subsequent phases are `awaiting_removal`, `rebooting`, or `reboot_failed`.
These retain `status: "running"` to block conflicting actions until the host
reboots, including when a manual restart is needed. Status is stored under
`/run` and resets on reboot; it is not a permanent clone history.
`POST /api/clone/scan` takes `{"source":"sd"}` or `{"source":"usb"}` and returns
source used/required bytes and targets with `fits`, `media`, `eligible`, and
`blocked_reason`. Unknown OS destinations also have `requires_sd_confirmation`
set to true. Only eligible targets receive a one-use token.
`POST /api/clone/start` takes the token and a `confirmation` matching the displayed
device name. An unknown OS destination additionally requires the JSON boolean
`"sd_confirmed": true`, supplied only after the user verifies the SD card and
OS copy. Both endpoints require the usual `X-Library-Token` header. Starting returns
immediately; poll state for the result. There is no cancel action once erasure
starts. A failed copy is not silently retried.

The root-only Unix socket `/run/library-clone/clone.sock` accepts bounded JSON
lines with `status`, `scan`, or `start` actions. It returns
`{"ok":true,"result":...}` or `{"ok":false,"error":"..."}`. State is saved in
`/run/library-clone/status.json`, allowing a restarted helper to report a copy
interrupted during this boot.

Run the downloader Python suite and JavaScript UI tests. Hardware commands in
clone tests are mocked; they never format a real disk. A local rsync regression
test uses temporary files to verify sparse allocation, hard links, and symlinks.
Pi acceptance testing:
verify protected/mounted disks are absent, reject an undersized destination,
clone 100 GB from a larger USB to a 128 GB stick, wait for the safe-removal prompt,
and confirm that the Library does not reboot until the destination is unplugged.
Check that it then boots with the original drive, and compare the clone's files
on another computer. Repeat with a smaller SD destination, verify it boots
with its separate Library_USB, and check a failed copy restores stopped readers
without rebooting. Also test unmount and reboot-request failures.

```sh
journalctl -u library-clone.service -b
systemctl status library-clone.socket
```
