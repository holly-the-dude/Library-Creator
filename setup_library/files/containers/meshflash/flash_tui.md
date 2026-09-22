# Meshtastic Offline TUI Flasher

> Implemented in this directory: see [README.md](README.md) for the current
> container build, browser terminal, USB mapping and SSH instructions. The
> browser uses ttyd to control the Pi’s TUI; the radio plugs into the Pi.
> The sections below are the original design notes, not the runtime script.
> Backup/restore and non-ESP32 devices remain outside the implementation.
> Library startup selects this setup terminal at `http://library:8086` when no
> USB radio completes a Meshtastic handshake. After flashing, reboot or rerun
> the radio startup check described in the README. Firmware offsets and required
> partitions come from release manifests; the examples below are not a substitute
> for the implemented validation in `prepare-offline.py` and `flasher.py`.

This guide shows how to build a completely offline, terminal-based Meshtastic firmware flasher using `esptool` and a simple TUI such as `dialog`.

The goal is to run the flasher on a Raspberry Pi or Linux system without requiring a browser, Node.js, Nuxt, GitHub access, or an Internet connection.

---

## Overview

The finished tool can provide a menu similar to:

```text
┌──────────── Meshtastic Offline Flasher ────────────┐
│                                                    │
│  Device: /dev/ttyUSB0                              │
│  Chip:   ESP32-S3                                  │
│                                                    │
│  Select board:                                     │
│                                                    │
│    > Heltec Wireless Stick Lite V3                 │
│      Heltec V3                                     │
│      LilyGo T-Beam                                 │
│      LilyGo T3-S3                                  │
│                                                    │
│                <Flash>   <Cancel>                  │
└────────────────────────────────────────────────────┘
```

Then select a firmware version:

```text
┌──────────── Firmware Version ────────────┐
│                                         │
│  > 2.7.26 Stable                        │
│    2.7.25 Stable                        │
│    2.7.24 Stable                        │
│                                         │
│       <Select>     <Cancel>             │
└─────────────────────────────────────────┘
```

The actual firmware flashing is performed by `esptool`.

---

# 1. Requirements

Install the following packages:

```bash
sudo apt update
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    dialog
```

Create a Python virtual environment:

```bash
sudo mkdir -p /opt/meshtastic-flasher
sudo chown "$USER":"$USER" /opt/meshtastic-flasher

python3 -m venv /opt/meshtastic-flasher/venv
```

Install `esptool`:

```bash
/opt/meshtastic-flasher/venv/bin/pip install esptool
```

Optionally install the Meshtastic Python CLI:

```bash
/opt/meshtastic-flasher/venv/bin/pip install meshtastic
```

The Meshtastic CLI is useful for checking whether Meshtastic is already installed on a device.

---

# 2. Directory Layout

Use a structure similar to:

```text
/opt/meshtastic-flasher/
├── flash.sh
├── boards.json
├── firmware/
│   ├── 2.7.26/
│   │   ├── firmware-heltec-v3.factory.bin
│   │   ├── firmware-heltec-wsl-v3.factory.bin
│   │   ├── firmware-tbeam-s3-core.factory.bin
│   │   └── ...
│   │
│   └── 2.7.25/
│       ├── firmware-heltec-v3.factory.bin
│       ├── firmware-heltec-wsl-v3.factory.bin
│       └── ...
│
└── venv/
```

Keep all firmware files locally under the `firmware` directory.

Once those firmware files are present, Internet access is not required.

---

# 3. Detect Connected Serial Devices

Linux ESP32 boards normally appear as one of:

```text
/dev/ttyUSB0
/dev/ttyUSB1
/dev/ttyACM0
/dev/ttyACM1
```

You can list likely devices with:

```bash
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
```

A simple Bash loop:

```bash
for port in /dev/ttyUSB* /dev/ttyACM*; do
    [ -e "$port" ] || continue
    echo "Found: $port"
done
```

---

# 4. Detect the ESP32 Chip

Use `esptool` to identify the chip:

```bash
/opt/meshtastic-flasher/venv/bin/esptool \
    --port /dev/ttyUSB0 \
    chip-id
```

Typical output:

```text
Chip is ESP32-S3
Features: WiFi, BLE, Embedded Flash
Crystal is 40MHz
```

Depending on the board, you may see:

```text
ESP32
ESP32-S2
ESP32-S3
ESP32-C3
```

The TUI can parse this output and only show compatible Meshtastic boards.

Example:

```bash
CHIP=$(
    /opt/meshtastic-flasher/venv/bin/esptool \
        --port /dev/ttyUSB0 \
        chip-id 2>&1 |
    grep -oE 'ESP32(-S2|-S3|-C3)?' |
    head -1
)

echo "$CHIP"
```

---

# 5. Check Whether Meshtastic Is Already Installed

If the optional Meshtastic Python CLI is installed, try:

```bash
/opt/meshtastic-flasher/venv/bin/meshtastic \
    --port /dev/ttyUSB0 \
    --info
```

If Meshtastic is running and communicating correctly, the command should return node and firmware information.

If the command fails, that does not necessarily mean the board is bad. It may contain:

- another firmware
- corrupted firmware
- a bootloader only
- Meshtastic that is not currently responding

You can still reflash the board with `esptool`.

---

# 6. Put the Device Into Bootloader Mode

Most ESP32 boards automatically enter flashing mode.

If automatic flashing fails, manually enter the bootloader.

For many ESP32-S3 boards:

```text
1. Hold BOOT / PRG.
2. Press and release RESET / RST.
3. Release BOOT / PRG.
4. Start esptool.
```

Button names vary between manufacturers.

---

# 7. Test Communication Before Flashing

Before erasing anything, verify communication:

```bash
/opt/meshtastic-flasher/venv/bin/esptool \
    --chip esp32s3 \
    --port /dev/ttyUSB0 \
    --baud 115200 \
    flash-id
```

Typical output includes:

```text
Chip is ESP32-S3
Manufacturer: ...
Device: ...
Detected flash size: 8MB
```

A baud rate of `115200` is intentionally conservative and is useful when USB or serial communication has previously failed during flashing.

---

# 8. Flash Modes

The TUI should ideally provide two modes.

## Update Firmware

Use this when you want to update Meshtastic without intentionally wiping everything first.

```text
Update Firmware
```

## Erase and Install

Use this when:

- firmware is corrupted
- the board behaves strangely
- changing firmware families
- troubleshooting persistent boot problems
- performing a clean Meshtastic installation

```text
Erase & Install
```

---

# 9. Erase Flash

For an ESP32-S3:

```bash
/opt/meshtastic-flasher/venv/bin/esptool \
    --chip esp32s3 \
    --port /dev/ttyUSB0 \
    --baud 115200 \
    erase-flash
```

Older `esptool` releases may also accept:

```bash
erase_flash
```

After erasing, put the board back into bootloader mode if needed.

---

# 10. Flash a Factory Image

If you have a Meshtastic `.factory.bin` image that is intended to be flashed at address `0x0`, use:

```bash
/opt/meshtastic-flasher/venv/bin/esptool \
    --chip esp32s3 \
    --port /dev/ttyUSB0 \
    --baud 115200 \
    write-flash \
    0x0 \
    /opt/meshtastic-flasher/firmware/2.7.26/firmware-heltec-wsl-v3.factory.bin
```

Older `esptool` versions may use:

```bash
write_flash
```

instead of:

```bash
write-flash
```

Check your version:

```bash
/opt/meshtastic-flasher/venv/bin/esptool version
```

---

# 11. Important: Not Every Firmware File Uses Address 0x0

Do not assume every `.bin` file should be written at address `0x0`.

A Meshtastic release may contain separate files for:

```text
bootloader
partition table
OTA data
application firmware
filesystem
```

These can require different flash offsets.

A `.factory.bin` is generally the preferred image for a simple clean install when the release specifically provides one for that board.

Always verify the release's flash layout before adding a new board or firmware file to the offline flasher.

---

# 12. Basic TUI with dialog

Install `dialog`:

```bash
sudo apt install dialog
```

A simple device-selection menu:

```bash
#!/usr/bin/env bash

set -euo pipefail

PORT=$(dialog \
    --stdout \
    --title "Meshtastic Offline Flasher" \
    --menu "Select serial device" \
    15 60 8 \
    /dev/ttyUSB0 "USB serial device" \
    /dev/ttyUSB1 "USB serial device" \
    /dev/ttyACM0 "USB ACM device" \
    /dev/ttyACM1 "USB ACM device")

clear

echo "Selected: $PORT"
```

---

# 13. Automatically Build the Device Menu

Instead of hardcoding ports:

```bash
#!/usr/bin/env bash

set -euo pipefail

OPTIONS=()

for port in /dev/ttyUSB* /dev/ttyACM*; do
    [ -e "$port" ] || continue

    OPTIONS+=(
        "$port"
        "Serial Device"
    )
done

if [ "${#OPTIONS[@]}" -eq 0 ]; then
    dialog \
        --title "Meshtastic Offline Flasher" \
        --msgbox "No serial devices were found." \
        8 45

    clear
    exit 1
fi

PORT=$(dialog \
    --stdout \
    --title "Meshtastic Offline Flasher" \
    --menu "Select device" \
    18 70 10 \
    "${OPTIONS[@]}")

clear

echo "Selected device: $PORT"
```

---

# 14. Firmware Selection Menu

Example:

```bash
FIRMWARE=$(dialog \
    --stdout \
    --title "Meshtastic Firmware" \
    --menu "Select firmware" \
    18 75 10 \
    "2.7.26-wsl-v3" \
    "Heltec Wireless Stick Lite V3 - 2.7.26" \
    "2.7.26-heltec-v3" \
    "Heltec V3 - 2.7.26" \
    "2.7.26-tbeam" \
    "LilyGo T-Beam - 2.7.26")

clear
```

The selected value can then map to a local firmware path.

Example:

```bash
case "$FIRMWARE" in

    2.7.26-wsl-v3)
        IMAGE="/opt/meshtastic-flasher/firmware/2.7.26/firmware-heltec-wsl-v3.factory.bin"
        CHIP="esp32s3"
        ;;

    2.7.26-heltec-v3)
        IMAGE="/opt/meshtastic-flasher/firmware/2.7.26/firmware-heltec-v3.factory.bin"
        CHIP="esp32s3"
        ;;

    2.7.26-tbeam)
        IMAGE="/opt/meshtastic-flasher/firmware/2.7.26/firmware-tbeam.factory.bin"
        CHIP="esp32"
        ;;

esac
```

---

# 15. Choose Update or Clean Install

```bash
MODE=$(dialog \
    --stdout \
    --title "Flash Mode" \
    --menu "Select operation" \
    14 60 5 \
    update "Update Firmware" \
    erase "Erase Flash and Install")

clear
```

Then:

```bash
if [ "$MODE" = "erase" ]; then

    esptool \
        --chip "$CHIP" \
        --port "$PORT" \
        --baud 115200 \
        erase-flash

fi
```

Follow it with the firmware write.

---

# 16. Flash Firmware

Example:

```bash
esptool \
    --chip "$CHIP" \
    --port "$PORT" \
    --baud 115200 \
    write-flash \
    0x0 \
    "$IMAGE"
```

---

# 17. Verify the Flash

After flashing, reset the device.

Wait a few seconds:

```bash
sleep 5
```

Then try:

```bash
meshtastic \
    --port "$PORT" \
    --info
```

If successful, show:

```text
Meshtastic detected
Firmware installation successful
```

---

# 18. Handling Serial Errors

A common flashing error is:

```text
Writing at 0x47a37... (8%)

Error: No serial data received.
```

This normally means communication was lost during the flash.

Try the following:

1. Use a shorter or higher-quality USB cable.
2. Connect directly to the Raspberry Pi instead of through a USB hub.
3. Manually put the ESP32 into bootloader mode.
4. Lower the flashing speed to:

```bash
--baud 115200
```

If the connection is still unstable, test:

```bash
--baud 57600
```

For troubleshooting only, you can test an even slower rate.

---

# 19. Watch for USB Disconnects

In another terminal:

```bash
watch -n 1 'ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null'
```

If `/dev/ttyUSB0` disappears exactly when flashing fails, suspect:

- USB cable
- USB hub
- board power
- USB-to-serial interface
- Raspberry Pi USB power
- physical USB connector

---

# 20. Recommended Safety Checks

Before allowing a flash, the program should check:

```text
Serial device exists
        ↓
ESP chip detected
        ↓
Selected firmware exists
        ↓
Selected firmware matches chip family
        ↓
User confirms operation
        ↓
Flash
        ↓
Verify
```

Never automatically erase a board just because it was detected.

---

# 21. Suggested Main Menu

A useful final interface could be:

```text
┌────────── Meshtastic Offline Flasher ──────────┐
│                                                │
│  Connected Device                              │
│                                                │
│  Port:       /dev/ttyUSB0                      │
│  Chip:       ESP32-S3                          │
│  Flash:      8 MB                              │
│  Meshtastic: Detected                          │
│  Version:    2.7.25                            │
│                                                │
│  1. Update Firmware                            │
│  2. Erase & Install Meshtastic                 │
│  3. Device Information                         │
│  4. Backup Flash                               │
│  5. Restore Flash                              │
│  6. Exit                                       │
│                                                │
└────────────────────────────────────────────────┘
```

---

# 22. Optional Flash Backup

Before erasing a device, the TUI could offer to back it up.

For an 8 MB board:

```bash
esptool \
    --chip esp32s3 \
    --port /dev/ttyUSB0 \
    --baud 115200 \
    read-flash \
    0x0 \
    0x800000 \
    backup.bin
```

This creates a full flash backup.

To restore it:

```bash
esptool \
    --chip esp32s3 \
    --port /dev/ttyUSB0 \
    --baud 115200 \
    write-flash \
    0x0 \
    backup.bin
```

Verify the actual flash size before performing a full backup.

---

# 23. Possible boards.json Format

Instead of hardcoding boards in Bash, keep board information in a JSON file:

```json
{
  "heltec-wsl-v3": {
    "name": "Heltec Wireless Stick Lite V3",
    "chip": "esp32s3",
    "firmware": "firmware-heltec-wsl-v3.factory.bin"
  },

  "heltec-v3": {
    "name": "Heltec LoRa 32 V3",
    "chip": "esp32s3",
    "firmware": "firmware-heltec-v3.factory.bin"
  },

  "tbeam": {
    "name": "LilyGo T-Beam",
    "chip": "esp32",
    "firmware": "firmware-tbeam.factory.bin"
  }
}
```

This makes adding boards much easier.

---

# 24. Completely Offline Operation

Once installed, the flasher needs only:

```text
Linux / Raspberry Pi
        +
esptool
        +
dialog
        +
local Meshtastic firmware
```

Optional:

```text
Meshtastic Python CLI
```

No runtime connection is required to:

```text
GitHub
Meshtastic API servers
npm
pnpm
Nuxt
Google
CDNs
Internet DNS
```

This makes the TUI flasher a good fit for an offline Raspberry Pi library or emergency/off-grid system.

---

# 25. Recommended Final Architecture

```text
               Raspberry Pi
                    │
                    │ USB
                    ▼
              ESP32 LoRa Board
                    │
                    ▼
       ┌─────────────────────────┐
       │ Meshtastic TUI Flasher │
       ├─────────────────────────┤
       │ dialog                  │
       │ esptool                 │
       │ meshtastic CLI          │
       │ boards.json             │
       │ firmware/*.bin          │
       └─────────────────────────┘
                    │
                    ▼
             Completely Offline
```

---

# Summary

A fully offline Meshtastic TUI flasher is practical and does not require the Meshtastic web flasher.

The basic workflow is:

```text
Detect USB device
        ↓
Detect ESP32 chip
        ↓
Check for existing Meshtastic
        ↓
Select board
        ↓
Select firmware
        ↓
Choose Update or Erase & Install
        ↓
Flash with esptool
        ↓
Verify Meshtastic
```

Using `esptool` directly keeps the system simple, reliable, and easy to maintain on a Raspberry Pi.
