# Library USB Downloader

Use Library USB Downloader to fill a USB drive directly from your Windows, Linux, or macOS computer without using the Library interface.

During Library installation, these downloader files are copied to `/Library/downloader`. Open that folder and follow the instructions for your computer below. If you are using another computer, copy the matching application or installer to that computer first.

## Windows

Double-click `library-usb-downloader.exe` to launch the downloader. No installation is required.

## macOS

Double-click `Library USB Downloader.app` to launch the downloader. No installation is required. When copying it to another Mac, copy the entire `.app` bundle.

## Linux

Open a terminal in `/Library/downloader` (or the folder where you copied the installer). Choose the package that matches your distribution and processor:

| Processor | Debian / Ubuntu package | Fedora / Red Hat package |
| --- | --- | --- |
| Intel or AMD 64-bit | `Library USB Downloader_0.2.0_amd64.deb` | `Library USB Downloader-0.2.0-1.x86_64.rpm` |
| ARM 64-bit | `Library USB Downloader_0.2.0_arm64.deb` | `Library USB Downloader-0.2.0-1.aarch64.rpm` |

Run `uname -m` if you are unsure: `x86_64` means Intel or AMD 64-bit; `aarch64` or `arm64` means ARM 64-bit.

### Debian / Ubuntu

For Intel or AMD 64-bit:

```bash
cd /Library/downloader
sudo apt install './Library USB Downloader_0.2.0_amd64.deb'
```

For ARM 64-bit:

```bash
cd /Library/downloader
sudo apt install './Library USB Downloader_0.2.0_arm64.deb'
```

The included `debian.sh` is also an example for Intel or AMD 64-bit systems. It installs the package with `dpkg`:

```bash
cd /Library/downloader
sudo bash debian.sh
```

If that reports missing dependencies, run `sudo apt --fix-broken install` to resolve them.

### Fedora / Red Hat

For ARM 64-bit:

```bash
cd /Library/downloader
sudo dnf install './Library USB Downloader-0.2.0-1.aarch64.rpm'
```

For Intel or AMD 64-bit:

```bash
cd /Library/downloader
sudo dnf install './Library USB Downloader-0.2.0-1.x86_64.rpm'
```

After installation, open **Library USB Downloader** from your applications menu.

## Fill your USB drive

1. Connect your computer to the internet.
2. Plug in your USB drive and launch Library USB Downloader.
3. Use the downloader to choose the USB drive and the content you want to download.
4. Start the download and keep the drive connected until it finishes.
5. Safely eject the USB drive before unplugging it.
