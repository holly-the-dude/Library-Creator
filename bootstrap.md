# bootstrap_modern - Library Installer for Raspberry Pi

## Overview

`bootstrap_modern` is an interactive, color-coded, menu-driven installer for setting up the Library system on a Raspberry Pi. It replaces the original `bootstrap` script's command-line argument approach with a full terminal UI featuring colored output and guided menus.

## Features

- **Color-coded output** — Status messages use distinct colors for quick visual parsing:
  - 🔵 `[INFO]` — Informational messages (Blue)
  - 🟢 `[  OK]` — Success confirmations (Green)
  - 🟡 `[WARN]` — Warnings requiring attention (Yellow)
  - 🔴 `[FAIL]` — Errors and failures (Red)
  - 🟣 `[STEP]` — Major progress steps (Magenta)
- **Interactive menus** — No need to remember CLI arguments
- **Unicode box-drawing** — Clean visual banners and separators
- **Auto-resume** — Survives reboots via crontab (`--auto` flag)
- **Progress tracking** — Boot stage flags show installation state
- **Confirmation prompts** — Destructive actions require explicit approval

## Requirements

- Raspberry Pi (tested on Pi 3/4/5)
- Raspberry Pi OS (Debian-based)
- Root access
- TFT display (3.5" or 2.4")
- Network connectivity (WiFi or Ethernet)
- USB drive (optional, for Library storage)

## Installation

Copy the script to the Pi's root home directory:

```bash
cp bootstrap_modern /root/bootstrap_modern
chmod +x /root/bootstrap_modern
```

## Usage

### Interactive Mode

Simply run the script without arguments:

```bash
./bootstrap_modern
```

This presents the main menu:

```
╔══════════════════════════════════════════════════╗
║       Library Bootstrap Installer               ║
║       Raspberry Pi Edition                      ║
║       version 1.0                               ║
╚══════════════════════════════════════════════════╝

  Main Menu
──────────────────────────────────────────────────
  1) Fresh Install          - Full installation from scratch
  2) Reinstall              - Remove existing and reinstall
  3) Resume Install         - Continue interrupted install
  4) System Status          - Check installation progress
  5) Advanced Options       - Manual boot stage selection
  q) Quit
──────────────────────────────────────────────────
  Select option:
```

### Auto Mode (Crontab)

After the first boot stage, the script installs a crontab entry that calls:

```bash
/root/bootstrap_modern --auto
```

This mode:
- Checks the system uptime (must be within 5 minutes of boot)
- Verifies no ansible-playbook is already running
- Automatically runs the next pending boot stage
- Exits silently if outside the run window

## Menu Options

### 1) Fresh Install

Performs a complete installation from scratch:

1. Prompts for display type (TFT 3.5" or TFT 2.4")
2. Prompts for the install archive password
3. Shows a configuration summary and asks for confirmation
4. Executes the First Boot process

### 2) Reinstall

Removes all installation progress to allow starting over:

- Clears boot flags (`.0boot`, `.firstboot`, `.secondboot`, `.thirdboot`)
- Removes the `install/` and `display/` directories
- Removes all podman container images
- Requires confirmation before proceeding

### 3) Resume Install

Detects the current installation stage and continues from where it left off:

- If First Boot is complete but Second Boot isn't → runs Second Boot
- If Second Boot is complete but Third Boot isn't → runs Third Boot
- If all stages are complete → reports installation is done

### 4) System Status

Displays the current state of the installation:

```
  System Status
──────────────────────────────────────────────────
  First Boot:  COMPLETE
  Second Boot: COMPLETE
  Third Boot:  PENDING
  Boot Flag:   SET
──────────────────────────────────────────────────
  Uptime:      up 3 minutes
  Ansible:     NOT RUNNING
──────────────────────────────────────────────────
```

### 5) Advanced Options

Provides manual control over individual boot stages:

- **Run First Boot only** — Download and initial setup
- **Run Second Boot only** — Ansible playbook installation
- **Run Third Boot only** — Final configuration
- **Reset all boot flags** — Clear progress to start fresh
- **View install log** — Opens the install log in `less`

## Boot Stages

The installation is divided into three boot stages, each separated by a system reboot:

### First Boot

| Action | Description |
|--------|-------------|
| USB formatting | Formats inserted USB as exFAT labeled `Library_USB` |
| Download install files | Fetches and extracts `install.zip` from the depot |
| TFT display setup | Installs LCD drivers for the selected display |
| System packages | Installs Python, Ansible, Podman, and utilities |
| Crontab setup | Installs auto-resume cron entry |
| Network config | Sets WiFi country and power management |
| Reboot | Triggers reboot for next stage |

### Second Boot

| Action | Description |
|--------|-------------|
| Display splash | Shows "configuring" image on TFT |
| Stabilize | Waits 60 seconds for services to start |
| Ansible playbook | Runs `01_install_ansible.yml` for full app setup |
| Verification | Checks for `shutdown_library.service` |
| Reboot | Triggers reboot for final stage |

### Third Boot

| Action | Description |
|--------|-------------|
| Remove crontab | Clears the auto-resume cron entry |
| Display splash | Shows "read only" image on TFT |
| Network cleanup | Removes preconfigured network connection |
| Reboot | Final reboot into production mode |

## File Locations

| File | Purpose |
|------|---------|
| `/root/bootstrap_modern` | The installer script |
| `/root/.0boot` | Flag indicating auto-boot mode is active |
| `/root/.firstboot` | Flag indicating First Boot is complete |
| `/root/.secondboot` | Flag indicating Second Boot is complete |
| `/root/.thirdboot` | Flag indicating Third Boot is complete |
| `/root/install/` | Downloaded installation files |
| `/root/install.log` | Auto-mode output log |
| `/root/installplay.log` | Ansible playbook output log |
| `/Library/` | USB mount point for library storage |

## Differences from Original `bootstrap`

| Feature | `bootstrap` (original) | `bootstrap_modern` |
|---------|----------------------|-------------------|
| Interface | CLI arguments | Interactive menus |
| Display selection | `./bootstrap pw tft35` | Menu prompt |
| Password | CLI argument | Secure prompt (hidden input) |
| Reinstall | `./bootstrap pw tft35 reinstall` | Menu option with confirmation |
| Output | Plain text boxes | Color-coded status messages |
| Resume | Run script again after reboot | Menu option or `--auto` flag |
| Status check | None | Dedicated status screen |
| Error visibility | Easy to miss | Red highlighted failures |

## Troubleshooting

### Script won't auto-resume after reboot

Check that the crontab entry exists:
```bash
cat /var/spool/cron/crontabs/root
```

Expected content:
```
* * * * * /root/bootstrap_modern --auto 2>&1 | /usr/bin/tee -a /root/install.log
```

### "Outside of run window" message

The auto-resume mode only runs within 5 minutes of boot. If the system has been up longer, run the script manually in interactive mode.

### Ansible playbook fails

Check the log:
```bash
less /root/installplay.log
```

Use **Advanced Options → Reset all boot flags** if you need to retry from scratch.

### Colors not displaying

Ensure your terminal supports ANSI color codes. SSH clients like PuTTY or modern terminal emulators all support this. If connecting via serial console, colors may not render properly.

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-08-21 | Initial release — menu-driven rewrite of bootstrap v13.5 |
