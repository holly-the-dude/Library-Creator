#!/usr/bin/python3
"""Host-only clone bridge. Never run in the downloader container.
V1.3
Fixed JSON actions over a root-only systemd socket; no caller-supplied commands.
All destructive work is confined to a recently inspected, unused USB disk.
"""
import copy
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import socketserver
import subprocess
import tempfile
import threading
import time

MIB = 1024 ** 2
TOOLS = ('lsblk', 'findmnt', 'sfdisk', 'udevadm', 'mkfs.vfat', 'mkfs.ext4',
         'mkfs.exfat', 'mount', 'umount', 'rsync', 'blkid', 'podman', 'systemctl')


def run(*args, input=None, timeout=60):
    result = subprocess.run(args, input=input, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        raise ValueError(f"{args[0]} failed: {result.stderr.strip()[-1200:]}")
    return result.stdout.strip()


def copy_files(args, update):
    """Stream rsync counters without buffering hours of progress in memory."""
    with tempfile.TemporaryFile(mode='w+') as errors:
        with subprocess.Popen(['rsync', '--info=progress2', *args], text=True,
                              stdout=subprocess.PIPE, stderr=errors) as process:
            last = 0
            copied = 0
            for line in process.stdout:
                match = re.match(r'\s*([\d,]+)\s+\d+%', line)
                if match:
                    copied = int(match[1].replace(',', ''))
                    if time.monotonic() - last >= 1:
                        update(copied=copied)
                        last = time.monotonic()
            if process.wait():
                errors.seek(0)
                raise ValueError('Copy failed: ' + errors.read()[-1200:])
            update(copied=copied)  # Publish the final counter even inside the throttle window.


def walk(node):
    yield node
    for child in node.get('children', []):
        yield from walk(child)


def inventory():
    return json.loads(run('lsblk', '--json', '--bytes', '--paths', '--output',
        'NAME,TYPE,SIZE,RO,TRAN,MODEL,SERIAL,MAJ:MIN,MOUNTPOINTS,FSTYPE,LABEL,UUID,PARTUUID,LOG-SEC'))['blockdevices']


def mounted_device(path, disks):
    # Match the filesystem by device number, never by an ambiguous label.
    number = run('findmnt', '--noheadings', '--mountpoint', path, '--output', 'MAJ:MIN')
    matches = [(disk, node) for disk in disks for node in walk(disk)
               if node.get('maj:min') == number]
    if len(matches) != 1 or matches[0][0]['type'] != 'disk':
        raise ValueError(f'{path} must be a mounted partition on a plain disk')
    return matches[0]


def used(path):
    usage = os.statvfs(path)
    return (usage.f_blocks - usage.f_bfree) * usage.f_frsize


def check_copy_capacity(path, required, filesystem):
    """Check actual writable space after formatting, not just raw disk size."""
    usage = os.statvfs(path)
    available = usage.f_bavail * usage.f_frsize
    if available < required:
        raise ValueError(f'{filesystem} destination has only {available / MIB:.1f} MiB available '
                         f'after formatting; at least {required / MIB:.1f} MiB is needed. '
                         'Use a larger destination or free space on the source and scan again.')


def copy_root(source, destination, update):
    # Space estimates use allocated blocks. Preserve sparse files so holes do
    # not expand into allocated zero-filled blocks on the new ext4 filesystem.
    args = ['-aHAXx', '--sparse', '--numeric-ids', '--exclude=/Library/*',
            '--exclude=/dev/*', '--exclude=/proc/*', '--exclude=/sys/*',
            '--exclude=/run/*', '--exclude=/tmp/*', '--exclude=/mnt/*',
            '--exclude=/media/*', '--exclude=/lost+found', source, str(destination) + '/']
    copy_files(args, update)


def identity(disk):
    # diskseq changes even if an unplugged disk is replaced with an identical
    # model on the same /dev/sdX. Fail closed on kernels without diskseq.
    seq = (Path('/sys/class/block') / Path(disk['name']).name / 'diskseq').read_text().strip()
    return [disk['name'], disk['maj:min'], disk.get('serial'), disk['size'], seq]


def native_sd(disk):
    """The MMC subsystem exposes the card type, unlike USB mass storage."""
    name = Path(disk['name']).name
    if not re.fullmatch(r'mmcblk\d+', name):
        return False
    try:
        return (Path('/sys/class/block') / name / 'device/type').read_text().strip() == 'SD'
    except OSError:
        return False


def media_type(disk):
    """Require reported SD *media*, never a model-name guess or reader capability.

    UDisks distinguishes ID_DRIVE_FLASH_SD (reader support) from
    ID_DRIVE_MEDIA_FLASH_SD/SDHC/SDXC (inserted media). Unknown requires
    explicit user verification for an OS clone; names are not proof.
    """
    if native_sd(disk):
        return 'sd'
    try:
        properties = dict(line.split('=', 1) for line in
                          run('udevadm', 'info', '--query=property', '--name', disk['name']).splitlines()
                          if '=' in line)
    except (ValueError, OSError, subprocess.SubprocessError):
        return 'unknown'
    sd_keys = {'ID_DRIVE_MEDIA_FLASH_SD', 'ID_DRIVE_MEDIA_FLASH_SDHC', 'ID_DRIVE_MEDIA_FLASH_SDXC'}
    other_media = any(value == '1' and key.startswith('ID_DRIVE_MEDIA_')
                      and key not in sd_keys | {'ID_DRIVE_MEDIA_FLASH'}
                      for key, value in properties.items())
    if properties.get('ID_DRIVE_THUMB') == '1' or other_media:
        return 'other'
    if any(properties.get(key) == '1' for key in sd_keys):
        return 'sd'
    return 'unknown'


def target_ok(disk, protected, kind=None):
    if (disk['type'] != 'disk' or (disk.get('tran') != 'usb' and not (kind == 'sd' and native_sd(disk)))
            or disk['name'] in protected or disk.get('ro') or not disk.get('size')):
        return False
    for node in walk(disk):
        if node.get('ro') or any(node.get('mountpoints') or []):
            return False
        if node['type'] not in ('disk', 'part'):
            return False
        holders = Path('/sys/class/block') / Path(node['name']).name / 'holders'
        if not holders.is_dir() or any(holders.iterdir()):
            return False
    return True


def validate_boot_source(root, boot):
    """Reject unsupported boot references before offering a destructive action."""
    def references(node):
        return {node['name']} | {f'{key.upper()}={node[key]}' for key in ('uuid', 'partuuid', 'label') if node.get(key)}
    mounts = {}
    for line in Path('/etc/fstab').read_text().splitlines():
        fields = line.split()
        if len(fields) >= 2 and not line.lstrip().startswith('#') and fields[1] in ('/', '/boot/firmware'):
            if fields[1] in mounts:
                raise ValueError('Duplicate boot/root mounts in fstab')
            mounts[fields[1]] = fields[0]
    if mounts.get('/') not in references(root) or mounts.get('/boot/firmware') not in references(boot):
        raise ValueError('SD cloning requires standard root and boot device references in fstab')
    roots = re.findall(r'(?<!\S)root=(\S+)', Path('/boot/firmware/cmdline.txt').read_text())
    if len(roots) != 1 or roots[0] not in references(root):
        raise ValueError('SD cloning requires a standard root= reference in cmdline.txt')


def source_info(kind, disks):
    root_disk, root = mounted_device('/', disks)
    lib_disk, lib = mounted_device('/Library', disks)
    protected = {root_disk['name'], lib_disk['name']}
    if kind == 'usb':
        if lib.get('label') != 'Library_USB' or lib.get('fstype') != 'exfat':
            raise ValueError('/Library must be the mounted exFAT Library_USB drive')
        if run('findmnt', '--submounts', '--mountpoint', '/Library', '--noheadings', '--output', 'TARGET').splitlines() != ['/Library']:
            raise ValueError('Unmount nested filesystems inside /Library before cloning')
        amount = used('/Library')
        return {'kind': kind, 'device': lib['name'], 'used': amount,
                'required': amount + max(256 * MIB, amount // 20) + 16 * MIB,
                'identity': identity(lib_disk)}, protected
    if kind != 'sd':
        raise ValueError('Choose sd or usb')
    boot_disk, boot = mounted_device('/boot/firmware', disks)
    protected.add(boot_disk['name'])
    if (root_disk['name'] != '/dev/mmcblk0' or boot_disk['name'] != root_disk['name']
            or root['name'] != '/dev/mmcblk0p2' or boot['name'] != '/dev/mmcblk0p1'
            or root.get('fstype') != 'ext4' or boot.get('fstype') != 'vfat'
            or len(root_disk.get('children', [])) != 2):
        raise ValueError('SD cloning requires the standard Pi SD layout: FAT /boot/firmware and ext4 /')
    validate_boot_source(root, boot)
    amount = used('/')
    boot_used = used('/boot/firmware')
    boot_size = max(512 * MIB, ((boot_used + 128 * MIB + MIB - 1) // MIB) * MIB)
    return {'kind': kind, 'device': root_disk['name'], 'used': amount + boot_used,
            'root_used': amount, 'boot_used': boot_used,
            'required': boot_size + amount + max(512 * MIB, amount // 10) + 16 * MIB,
            'boot_size': boot_size, 'root': root, 'boot': boot,
            'identity': identity(root_disk)}, protected


def inspect(kind):
    for tool in TOOLS:
        if not shutil.which(tool):
            raise ValueError(f'Host clone dependency missing: {tool}')
    disks = inventory()
    info, protected = source_info(kind, disks)
    # Always protect boot too, including when cloning the USB drive.
    boot_disk, _ = mounted_device('/boot/firmware', disks)
    protected.add(boot_disk['name'])
    targets = []
    for disk in disks:
        if target_ok(disk, protected, kind):
            if kind == 'sd' and (disk.get('log-sec') != 512 or disk['size'] >= 2 * 1024 ** 4):
                continue
            try:
                fingerprint = identity(disk)
            except OSError:
                continue
            media = media_type(disk)
            eligible = kind != 'sd' or media in {'sd', 'unknown'}
            reason = '' if eligible else 'OS clones require an SD card. This device reports another media type.'
            targets.append({'device': disk['name'], 'size': disk['size'],
                            'media': media, 'eligible': eligible, 'blocked_reason': reason,
                            'requires_sd_confirmation': kind == 'sd' and media == 'unknown',
                            'model': (disk.get('model') or 'USB device').strip(),
                            'serial': disk.get('serial') or '', 'identity': fingerprint,
                            'fits': disk['size'] >= info['required']})
    return info, targets


def partition(disk, number):
    return disk + ('p' if disk[-1].isdigit() else '') + str(number)


def sd_partition_layout(boot_size):
    # Without an explicit second start, sfdisk can put root in the free 1–8 MiB
    # gap before boot. Root must begin after boot and fill the remaining disk.
    boot_mib = boot_size // MIB
    return (f'label: dos\nlabel-id: 0x{secrets.token_hex(4)}\n'
            f'start=8MiB, size={boot_mib}MiB, type=c\n'
            f'start={8 + boot_mib}MiB, type=83\n')


def rewrite_boot(root, source, root_part, boot_part):
    """Fresh UUIDs avoid collisions while source and clone are both attached."""
    ids = {}
    for old, new in ((source['root'], root_part), (source['boot'], boot_part)):
        ids[old['name']] = new
        for key in ('uuid', 'partuuid'):
            if old.get(key):
                ids[f'{key.upper()}={old[key]}'] = f'{key.upper()}={run("blkid", "-s", key.upper(), "-o", "value", new)}'
        if old.get('label'):
            ids[f'LABEL={old["label"]}'] = 'UUID=' + run('blkid', '-s', 'UUID', '-o', 'value', new)
    fstab = root / 'etc/fstab'
    lines = []
    for line in fstab.read_text().splitlines(keepends=True):
        fields = line.split()
        if fields and not line.lstrip().startswith('#') and len(fields) >= 2 and fields[1] in ('/', '/boot/firmware'):
            if fields[0] not in ids:
                raise ValueError('Unsupported source in cloned fstab')
            # Use UUID even for a source mounted by /dev/mmcblk0pX.
            dest = root_part if fields[1] == '/' else boot_part
            line = line.replace(fields[0], 'UUID=' + run('blkid', '-s', 'UUID', '-o', 'value', dest), 1)
        lines.append(line)
    fstab.write_text(''.join(lines))
    cmdline = root / 'boot/firmware/cmdline.txt'
    text = cmdline.read_text()
    if len(re.findall(r'(?<!\S)root=\S+', text)) != 1:
        raise ValueError('Expected one root= entry in cmdline.txt')
    text = re.sub(r'(?<!\S)root=\S+', 'root=PARTUUID=' + run('blkid', '-s', 'PARTUUID', '-o', 'value', root_part), text)
    cmdline.write_text(text)


class Cloner:
    def __init__(self, state_path=None):
        self.state_path = Path(state_path) if state_path else None
        self.lock = threading.RLock()
        self.plans = {}
        self.state = {'status': 'idle', 'message': 'Choose a source, insert a destination, then scan.'}
        if self.state_path and self.state_path.exists():
            try:
                self.state = json.loads(self.state_path.read_text())
                if self.state['status'] == 'running':
                    if self.state.get('copy_complete'):
                        self.state.update(phase='reboot_failed', message='Clone was safely unmounted, but automatic restart was interrupted. Remove the destination and restart the Library manually.')
                    else:
                        self.state.update(status='failed', message='Clone interrupted. Check destination mounts and restart stopped Library readers before retrying.')
            except (OSError, ValueError, KeyError):
                self.state = {'status': 'failed', 'message': 'Previous clone status could not be read. Check host logs.'}

    def status(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def update(self, **values):
        with self.lock:
            self.state.update(values)
            if self.state_path:
                temporary = self.state_path.with_suffix('.tmp')
                temporary.write_text(json.dumps(self.state))
                temporary.replace(self.state_path)

    def scan(self, kind):
        with self.lock:
            if self.state['status'] == 'running':
                raise ValueError('A clone is already running')
            info, targets = inspect(kind)
            self.plans = {}  # Each scan invalidates old confirmations.
            for target in targets:
                if target.get('eligible', True):
                    token = secrets.token_urlsafe(32)
                    self.plans[token] = (time.monotonic(), info, copy.deepcopy(target))
                    target['token'] = token
                target.pop('identity')
            return {'source': {k: info[k] for k in ('kind', 'device', 'used', 'required')},
                    'targets': targets}

    def start(self, token, confirmation, sd_confirmed=False):
        with self.lock:
            if self.state['status'] == 'running':
                raise ValueError('A clone is already running')
            plan = self.plans.get(token) if isinstance(token, str) else None
            if not plan or time.monotonic() - plan[0] > 300:
                raise ValueError('Scan again; destination selection expired')
            _, info, planned_target = plan
            target = copy.deepcopy(planned_target)
            target['sd_confirmed'] = sd_confirmed is True
            if info['kind'] == 'sd' and target.get('media') == 'unknown' and not target['sd_confirmed']:
                raise ValueError('Verify that the destination is an SD card and that you intend to copy the operating system.')
            if confirmation != target['device']:
                raise ValueError('Confirm the destination device name to erase it')
            self.revalidate(info, target)
            self.plans.clear()
            self.state = {'status': 'running', 'phase': 'preparing', 'message': 'Preparing clone…',
                          'source': info['kind'], 'destination': target['device']}
            self.update(**self.state)
            threading.Thread(target=self.worker, args=(info, target), daemon=True).start()
            return self.status()

    def revalidate(self, info, target):
        fresh, targets = inspect(info['kind'])
        match = next((t for t in targets if t['identity'] == target['identity']), None)
        if info['kind'] == 'sd':
            if not match or not match.get('eligible') or match.get('media') not in {'sd', 'unknown'}:
                raise ValueError('OS clones require an SD card. This destination is not eligible; scan again.')
            if match['media'] == 'unknown' and target.get('sd_confirmed') is not True:
                raise ValueError('SD media is unidentified. Scan again and verify the SD card and operating-system copy.')
        if fresh['identity'] != info['identity'] or not match or not match['fits']:
            raise ValueError('Source/destination changed, is in use, or is too small. Scan again.')
        return fresh

    def worker(self, info, target):
        stopped = []
        mounts = []
        scratch = None
        error = None
        try:
            self.update(phase='stopping', containers_done=0, containers_total=None,
                        message='Finding Library containers to stop…')
            running = json.loads(run('podman', 'ps', '--format', 'json'))
            readers = []
            for container in running:
                names = container.get('Names') or []
                if isinstance(names, str):
                    names = [names]
                # Hotspot keeps the browser connection alive. Downloader blocks writes.
                if 'data_download' in names or 'hotspot' in container.get('Image', ''):
                    continue
                readers.append(container)
            self.update(containers_total=len(readers))
            for number, container in enumerate(readers):
                cid = container['Id']
                names = container.get('Names') or [cid[:12]]
                name = names if isinstance(names, str) else names[0]
                self.update(message=f'Stopping container {number + 1} of {len(readers)}: {name}…')
                stopped.append(cid)
                run('podman', 'stop', '--time', '30', cid, timeout=90)
                self.update(containers_done=number + 1)
            info = self.revalidate(info, target)  # Last check before any disk writes.
            disk = target['device']
            self.update(phase='formatting', message='Partitioning and formatting destination…')
            if info['kind'] == 'sd':
                layout = sd_partition_layout(info['boot_size'])
            else:
                layout = 'label: gpt\nstart=8MiB, type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7\n'
            run('sfdisk', '--wipe', 'always', '--wipe-partitions', 'always', disk, input=layout)
            run('udevadm', 'settle')
            first = partition(disk, 1)
            last = partition(disk, 2) if info['kind'] == 'sd' else first
            for _ in range(50):
                if Path(first).exists() and Path(last).exists():
                    break
                time.sleep(.1)
            else:
                raise ValueError('Destination partitions did not appear')
            if info['kind'] == 'sd':
                run('mkfs.vfat', '-F', '32', '-n', 'bootfs', first)
                run('mkfs.ext4', '-F', '-m', '0', '-L', 'rootfs', last, timeout=600)
            else:
                run('mkfs.exfat', '-L', 'Library_USB', first, timeout=600)
            scratch = Path(tempfile.mkdtemp(prefix='library-clone-', dir='/mnt'))
            run('mount', last, str(scratch))
            mounts.append(scratch)
            if info['kind'] == 'sd':
                check_copy_capacity(scratch, info['root_used'], 'SD root')
                self.update(phase='copying_root', copied=0, copy_total=info['root_used'],
                            message='Copying SD root filesystem…')
                copy_root('/', scratch, self.update)
                boot = scratch / 'boot/firmware'
                boot.mkdir(parents=True, exist_ok=True)
                run('mount', first, str(boot))
                mounts.append(boot)
                check_copy_capacity(boot, info['boot_used'], 'SD boot')
                self.update(phase='copying_boot', copied=0, copy_total=info['boot_used'],
                            message='Copying SD boot files…')
                copy_files(['-rtx', '--modify-window=2', '/boot/firmware/', str(boot) + '/'], self.update)
                rewrite_boot(scratch, info, last, first)
                for name in ('dev', 'proc', 'sys', 'run', 'tmp', 'mnt', 'media', 'Library'):
                    (scratch / name).mkdir(exist_ok=True)
                (scratch / 'tmp').chmod(0o1777)
            else:
                check_copy_capacity(scratch, info['used'], 'Library_USB')
                self.update(phase='copying_usb', copied=0, copy_total=info['used'],
                            message='Copying Library_USB files… This can take several hours.')
                copy_files(['-rtx', '--modify-window=2', '/Library/', str(scratch) + '/'], self.update)
            self.update(phase='finalizing', message='Flushing files and safely unmounting destination…')
            os.sync()
        except Exception as exc:
            error = str(exc)
            # Keep capacity evidence before cleanup unmounts the destination.
            if mounts and self.status().get('phase', '').startswith('copying_'):
                try:
                    usage = os.statvfs(mounts[-1])
                    error += (f' Destination filesystem: {usage.f_bavail * usage.f_frsize / MIB:.1f} MiB free '
                              f'of {usage.f_blocks * usage.f_frsize / MIB:.1f} MiB; '
                              f'{usage.f_favail} free inodes.')
                except OSError:
                    pass  # Retain the original copy failure if the device vanished.
        finally:
            cleanup_errors = []
            if error:
                self.update(phase='finalizing', message='Cleaning up after copy failure…')
            for path in reversed(mounts):
                try:
                    run('umount', str(path), timeout=120)
                except Exception as exc:
                    cleanup_errors.append(str(exc))
            if scratch and not cleanup_errors:
                try:
                    scratch.rmdir()
                except OSError as exc:
                    cleanup_errors.append(str(exc))
            if error or cleanup_errors:
                # A failed copy must not trigger a reboot. Try to restore readers
                # so the Library remains usable while the failure is investigated.
                self.update(phase='restarting', containers_done=0, containers_total=len(stopped),
                            message='Restoring Library containers after clone failure…')
                restarted = 0
                for cid in stopped:
                    try:
                        run('podman', 'start', cid, timeout=120)
                        restarted += 1
                        self.update(containers_done=restarted)
                    except Exception as exc:
                        cleanup_errors.append(str(exc))
                self.update(status='failed', phase='failed', message='; '.join(filter(None, [error] + cleanup_errors)) +
                            ' Clone is not confirmed complete. Check host logs/mounts before removing it.')
        if not error and not cleanup_errors:
            self.restart_after_removal(target['device'])

    def restart_after_removal(self, device):
        """Keep writes blocked until the safely unmounted clone is unplugged.

        Unmounting does not hide a duplicate Library_USB label at the next boot.
        Require physical removal before asking systemd to reboot; normal boot
        starts the readers again without issuing Podman starts in this process.
        """
        try:
            self.update(status='running', phase='awaiting_removal', copy_complete=True,
                        message=f'Copy complete. {device} is safely ejected. Unplug the destination drive; the Library will restart automatically. Leave the original drive connected.')
            device_path = Path('/sys/class/block') / Path(device).name
            while True:
                try:
                    device_path.stat()
                except FileNotFoundError:
                    break
                time.sleep(2)
            self.update(phase='rebooting', message='Destination removed. Restarting the Library… Keep power connected and reload this page when it is back online.')
            time.sleep(3)  # Give the browser a poll interval to display the message.
            # The general Library restart helper calls Podman again. Successful
            # clones instead use a normal systemd reboot, with no forced reboot.
            run('systemctl', 'reboot', '--no-block')
        except Exception as exc:
            self.update(status='running', phase='reboot_failed',
                        message=f'Copy complete and destination safely unmounted, but automatic restart failed: {exc}. Remove the destination if still connected and restart the Library manually.')


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(10)
        try:
            line = self.rfile.readline(8193)
            if len(line) > 8192 or not line.endswith(b'\n'):
                raise ValueError('Invalid request size')
            body = json.loads(line)
            if not isinstance(body, dict):
                raise ValueError('Expected a JSON object')
            action = body.get('action')
            if action == 'status':
                result = self.server.cloner.status()
            elif action == 'scan':
                result = self.server.cloner.scan(body.get('source'))
            elif action == 'start':
                result = self.server.cloner.start(body.get('token'), body.get('confirmation'), body.get('sd_confirmed', False))
            else:
                raise ValueError('Unknown clone action')
            response = {'ok': True, 'result': result}
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            response = {'ok': False, 'error': str(exc)}
        self.wfile.write(json.dumps(response).encode() + b'\n')


def main():
    if os.environ.get('LISTEN_PID') != str(os.getpid()) or os.environ.get('LISTEN_FDS') != '1':
        raise RuntimeError('Start through library-clone.socket')
    with socketserver.ThreadingUnixStreamServer('', Handler, bind_and_activate=False) as server:
        server.socket.close()
        server.socket = socket.socket(fileno=3)
        server.cloner = Cloner('/run/library-clone/status.json')
        server.serve_forever()


if __name__ == '__main__':
    main()
