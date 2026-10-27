"""Clone safety tests: every hardware command is mocked; never format a disk."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import clone_host as host

GIB = 1024 ** 3


def disk(name='/dev/sdb', size=128 * GIB, **values):
    return dict(name=name, size=size, type='disk', tran='usb', ro=False,
                model='Spare stick', serial='1234', mountpoints=[None], **values)


class CloneSafetyTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.object(Path, 'is_dir', return_value=True).start()
        patch.object(Path, 'iterdir', return_value=iter(())).start()
        self.source = {'kind': 'usb', 'device': '/dev/sda1', 'used': 100 * GIB,
                       'required': 106 * GIB, 'identity': ['source']}
        self.target = {'device': '/dev/sdb', 'size': 128 * GIB, 'fits': True,
                       'model': 'Spare', 'serial': '123', 'identity': ['target', 'diskseq-1']}
        self.inspect = patch.object(host, 'inspect', return_value=(self.source, [self.target])).start()
        self.cloner = host.Cloner()
        self.commands = patch.object(host, 'run').start()

    def plan(self):
        # Real inspect returns fresh objects each time.
        self.inspect.side_effect = lambda kind: (copy.deepcopy(self.source), [copy.deepcopy(self.target)])
        return self.cloner.scan('usb')['targets'][0]['token']

    def test_active_readonly_nonusb_and_mounted_devices_are_never_targets(self):
        self.assertTrue(host.target_ok(disk(), {'/dev/sda'}))
        self.assertFalse(host.target_ok(disk('/dev/sda'), {'/dev/sda'}))
        for key, value in [('ro', True), ('tran', 'sata'), ('mountpoints', ['/data'])]:
            candidate = disk(); candidate[key] = value
            self.assertFalse(host.target_ok(candidate, set()))
        for value in ['/Library', '/', '/boot/firmware', '[SWAP]']:
            candidate = disk(children=[dict(name='/dev/sdb1', type='part', mountpoints=[value])])
            self.assertFalse(host.target_ok(candidate, set()))
        candidate = disk(children=[dict(name='/dev/dm-0', type='crypt', mountpoints=[])])
        self.assertFalse(host.target_ok(candidate, set()))
        with patch.object(Path, 'iterdir', return_value=iter([Path('holder')])):
            self.assertFalse(host.target_ok(disk(), set()))

    def test_typed_confirmation_expiry_and_one_use(self):
        token = self.plan()
        with self.assertRaisesRegex(ValueError, 'Confirm'):
            self.cloner.start(token, '/dev/sda')
        with patch.object(host.time, 'monotonic', return_value=time.monotonic() + 301):
            with self.assertRaisesRegex(ValueError, 'expired'):
                self.cloner.start(token, '/dev/sdb')
        with patch.object(host.threading, 'Thread') as thread:
            result = self.cloner.start(token, '/dev/sdb')
            self.assertEqual(result['status'], 'running')
            thread.return_value.start.assert_called_once()
        self.commands.assert_not_called()
        self.cloner.update(status='complete')
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.cloner.start(token, '/dev/sdb')

    def test_device_replacement_source_change_mount_and_size_rechecked(self):
        for change in ['replacement', 'source', 'mounted', 'small']:
            with self.subTest(change=change):
                self.source['identity'] = ['source']
                self.target['identity'] = ['target', 'diskseq-1']
                self.target['fits'] = True
                token = self.plan()
                if change == 'replacement': self.target['identity'][-1] = 'diskseq-2'
                if change == 'source': self.source['identity'] = ['new-source']
                if change == 'small': self.target['fits'] = False
                if change == 'mounted': self.inspect.side_effect = lambda kind: (self.source, [])
                with self.assertRaisesRegex(ValueError, 'Scan again'):
                    self.cloner.start(token, '/dev/sdb')
                self.commands.assert_not_called()

    def test_rescan_invalidates_previous_selection(self):
        token = self.plan()
        self.plan()
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.cloner.start(token, '/dev/sdb')

    def test_used_data_not_source_capacity_determines_fit(self):
        self.commands.return_value = '/Library'
        source = disk('/dev/sda', size=512 * GIB)
        source['maj:min'] = '8:0'
        lib = {'name': '/dev/sda1', 'label': 'Library_USB', 'fstype': 'exfat'}
        with patch.object(host, 'mounted_device', side_effect=[(disk('/dev/mmcblk0'), {}), (source, lib)]), \
             patch.object(host, 'identity', return_value=['source']), patch.object(host, 'used', return_value=100 * GIB):
            info, protected = host.source_info('usb', [])
        self.assertLess(info['required'], 128 * GIB)
        self.assertGreater(info['required'], 100 * GIB)
        self.assertIn('/dev/sda', protected)

    def test_worker_rechecks_before_format_and_restores_stopped_containers(self):
        self.commands.side_effect = lambda *args, **kwargs: json.dumps([
            {'Id': 'reader', 'Names': ['wiki'], 'Image': 'localhost/wiki'},
            {'Id': 'wifi', 'Names': ['random'], 'Image': 'localhost/hotspot'},
            {'Id': 'downloader', 'Names': ['data_download'], 'Image': 'localhost/data_download'}
        ]) if args[:2] == ('podman', 'ps') else ''
        with patch.object(self.cloner, 'revalidate', side_effect=ValueError('drive replaced')):
            self.cloner.worker(self.source, self.target)
        calls = [c.args for c in self.commands.call_args_list]
        self.assertIn(('podman', 'stop', '--time', '30', 'reader'), calls)
        self.assertIn(('podman', 'start', 'reader'), calls)
        self.assertFalse(any(c[0] == 'sfdisk' for c in calls))
        self.assertFalse(any('wifi' in c or 'downloader' in c for c in calls))
        self.assertEqual(self.cloner.status()['status'], 'failed')


class MediaTests(unittest.TestCase):
    def test_usb_reader_capability_name_and_removable_flag_do_not_prove_sd_media(self):
        device = disk()
        device.update(model='SD MMC Card Reader', rm=True)
        for props in ('', 'ID_DRIVE_FLASH_SD=1\n', 'ID_DRIVE_FLASH_SD=1\nID_DRIVE_FLASH_MMC=1\n'):
            with self.subTest(props=props), patch.object(host, 'run', return_value=props):
                self.assertEqual(host.media_type(device), 'unknown')
        with patch.object(host, 'run', side_effect=ValueError('udev unavailable')):
            self.assertEqual(host.media_type(device), 'unknown')

    def test_sd_family_media_is_recognized_but_other_media_and_conflicts_are_rejected(self):
        for suffix in ('SD', 'SDHC', 'SDXC'):
            with self.subTest(suffix=suffix), patch.object(host, 'run', return_value=f'ID_DRIVE_MEDIA_FLASH_{suffix}=1\n'):
                self.assertEqual(host.media_type(disk()), 'sd')
        for props in ('ID_DRIVE_THUMB=1\n', 'ID_DRIVE_MEDIA_FLASH_MMC=1\n',
                      'ID_DRIVE_MEDIA_FLASH_SD=1\nID_DRIVE_MEDIA_FLASH_CF=1\n',
                      'ID_DRIVE_MEDIA_FLASH_SD=1\nID_DRIVE_THUMB=1\n'):
            with self.subTest(props=props), patch.object(host, 'run', return_value=props):
                self.assertEqual(host.media_type(disk()), 'other')

    def test_native_sd_is_supported_and_still_subject_to_mount_and_source_protection(self):
        device = disk('/dev/mmcblk1')
        device['tran'] = 'mmc'
        with patch.object(Path, 'read_text', return_value='SD\n'), \
             patch.object(Path, 'is_dir', return_value=True), \
             patch.object(Path, 'iterdir', side_effect=lambda: iter(())), patch.object(host, 'run') as run:
            self.assertEqual(host.media_type(device), 'sd')
            self.assertTrue(host.target_ok(device, set(), 'sd'))
            self.assertFalse(host.target_ok(device, {'/dev/mmcblk1'}, 'sd'))
            self.assertFalse(host.target_ok(device, set(), 'usb'))
            device['mountpoints'] = ['/data']
            self.assertFalse(host.target_ok(device, set(), 'sd'))
            run.assert_not_called()
        with patch.object(Path, 'read_text', return_value='MMC\n'):
            self.assertFalse(host.native_sd(device))

    def test_os_scan_blocks_unknown_usb_and_revalidates_media_before_erasure(self):
        source = {'kind': 'sd', 'device': '/dev/mmcblk0', 'identity': ['system'], 'used': GIB, 'required': 2 * GIB}
        devices = [disk('/dev/sdb', **{'log-sec': 512}), disk('/dev/sdc', **{'log-sec': 512}),
                   disk('/dev/sdd', **{'log-sec': 512})]
        media = {'/dev/sdb': 'sd', '/dev/sdc': 'other', '/dev/sdd': 'unknown'}
        with patch.object(host.shutil, 'which', return_value='/usr/bin/tool'), \
             patch.object(host, 'inventory', return_value=devices), \
             patch.object(host, 'source_info', return_value=(source, {'/dev/mmcblk0'})), \
             patch.object(host, 'mounted_device', return_value=({'name': '/dev/mmcblk0'}, {})), \
             patch.object(host, 'target_ok', return_value=True), \
             patch.object(host, 'identity', side_effect=lambda d: [d['name']]), \
             patch.object(host, 'media_type', side_effect=lambda d: media[d['name']]), \
             patch.object(host, 'run') as commands:
            cloner = host.Cloner()
            scan = cloner.scan('sd')
            self.assertEqual([t['eligible'] for t in scan['targets']], [True, False, True])
            self.assertIn('token', scan['targets'][0])
            self.assertNotIn('token', scan['targets'][1])
            self.assertIn('token', scan['targets'][2])
            self.assertTrue(scan['targets'][2]['requires_sd_confirmation'])
            token = scan['targets'][0]['token']
            media['/dev/sdb'] = 'unknown'  # Same identity and capacity, but no longer reported as SD.
            with self.assertRaisesRegex(ValueError, 'SD media is unidentified'):
                cloner.start(token, '/dev/sdb')
            self.assertEqual(cloner.status()['status'], 'idle')
            commands.assert_not_called()
            unknown_token = scan['targets'][2]['token']
            with patch.object(host.threading, 'Thread') as thread:
                for unverified in (False, None, 'true', 1):
                    with self.subTest(unverified=unverified), self.assertRaisesRegex(ValueError, 'Verify'):
                        cloner.start(unknown_token, '/dev/sdd', unverified)
                thread.assert_not_called()
                result = cloner.start(unknown_token, '/dev/sdd', True)
                self.assertEqual(result['status'], 'running')
                thread.return_value.start.assert_called_once()
                worker_info, worker_target = thread.call_args.kwargs['args']
                self.assertTrue(worker_target['sd_confirmed'])
                # The worker repeats checks with the same verified selection.
                cloner.revalidate(worker_info, worker_target)
                media['/dev/sdd'] = 'other'
                with self.assertRaisesRegex(ValueError, 'not eligible'):
                    cloner.revalidate(worker_info, worker_target)
            cloner.update(status='complete')
            # The restriction is specific to OS cloning; USB content copying still works.
            source['kind'] = 'usb'
            scan = cloner.scan('usb')
            self.assertTrue(all(t['eligible'] and 'token' in t for t in scan['targets']))


class WorkerTests(unittest.TestCase):
    def test_copy_layout_cleanup_and_reader_recovery(self):
        for kind, fails in [('usb', False), ('sd', False), ('usb', 'copy'), ('usb', 'unmount'), ('usb', 'sync')]:
            with self.subTest(kind=kind, fails=fails), tempfile.TemporaryDirectory() as tmp:
                scratch = Path(tmp) / 'mount'
                scratch.mkdir()
                info = {'kind': kind, 'boot_size': 512 * host.MIB, 'used': 1100,
                        'root_used': 1000, 'boot_used': 100}
                cloner = host.Cloner()
                commands = []
                phases = []
                def copying(args, update):
                    phases.append(cloner.status())
                    if fails == 'copy':
                        raise ValueError("copy broke")
                    update(copied=cloner.status()["copy_total"])
                def command(*args, **kwargs):
                    commands.append((args, kwargs))
                    if args[:2] == ('podman', 'stop'):
                        self.assertEqual(cloner.status()['phase'], 'stopping')
                        self.assertEqual(cloner.status()['containers_done'], 0)
                        self.assertEqual(cloner.status()['containers_total'], 1)
                    if args[:2] == ('podman', 'start'):
                        self.assertEqual(cloner.status()['phase'], 'restarting')
                    if args[:2] == ('podman', 'ps'):
                        return json.dumps([{'Id': 'reader', 'Names': ['wiki'], 'Image': 'wiki'}])
                    if args[0] == 'umount' and fails == 'unmount':
                        raise ValueError('unmount broke')
                    return ''
                def finish(device):
                    self.assertIn((('umount', str(scratch)), {'timeout': 120}), commands)
                    cloner.update(status='running', phase='awaiting_removal', copy_complete=True)
                with patch.object(host, 'run', side_effect=command), \
                     patch.object(cloner, 'revalidate', return_value=info), \
                     patch.object(host.tempfile, 'mkdtemp', return_value=str(scratch)), \
                     patch.object(host.Path, 'exists', return_value=True), \
                     patch.object(host.Path, 'rmdir'), \
                     patch.object(host.os, 'sync', side_effect=OSError('sync broke') if fails == 'sync' else None), \
                     patch.object(cloner, 'restart_after_removal', side_effect=finish) as restart, \
                     patch.object(host, 'rewrite_boot') as rewrite, \
                     patch.object(host, 'copy_files', side_effect=copying) as cp:
                    cloner.worker(info, {'device': '/dev/sdb'})
                args = [entry[0] for entry in commands]
                if fails:
                    self.assertIn(('podman', 'start', 'reader'), args)
                    restart.assert_not_called()
                    self.assertNotIn('copy_complete', cloner.status())
                else:
                    self.assertNotIn(('podman', 'start', 'reader'), args)
                    restart.assert_called_once_with('/dev/sdb')
                    self.assertTrue(cloner.status()['copy_complete'])
                self.assertIn(('umount', str(scratch)), args)
                self.assertEqual(cloner.status()['status'], 'failed' if fails else 'running')
                layout = next(kwargs['input'] for cmd, kwargs in commands if cmd[0] == 'sfdisk')
                if kind == 'sd':
                    self.assertEqual([(p['phase'], p['copied'], p['copy_total']) for p in phases],
                                     [('copying_root', 0, 1000), ('copying_boot', 0, 100)])
                    self.assertIn('label: dos', layout)
                    self.assertIn('size=512MiB', layout)
                    self.assertIn(('mkfs.ext4', '-F', '-m', '0', '-L', 'rootfs', '/dev/sdb2'), args)
                    self.assertIn('--exclude=/Library/*', cp.call_args_list[0].args[0])
                    self.assertIn('-aHAXx', cp.call_args_list[0].args[0])
                    rewrite.assert_called_once_with(scratch, info, '/dev/sdb2', '/dev/sdb1')
                    self.assertLess(args.index(('umount', str(scratch / 'boot/firmware'))), args.index(('umount', str(scratch))))
                else:
                    self.assertEqual([(p['phase'], p['copied'], p['copy_total']) for p in phases],
                                     [('copying_usb', 0, 1100)])
                    self.assertIn('label: gpt', layout)
                    self.assertIn(('mkfs.exfat', '-L', 'Library_USB', '/dev/sdb1'), args)
                    self.assertIn('/Library/', cp.call_args.args[0])
                    rewrite.assert_not_called()

    def test_interrupted_worker_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'status.json'
            state.write_text(json.dumps({'status': 'running', 'destination': '/dev/sdb'}))
            cloner = host.Cloner(state)
            self.assertEqual(cloner.status()['status'], 'failed')
            self.assertIn('interrupted', cloner.status()['message'])

    def test_success_waits_for_physical_removal_then_reboots_without_podman(self):
        cloner = host.Cloner()
        def waiting(seconds):
            if seconds == 2:
                self.assertEqual(cloner.status()['phase'], 'awaiting_removal')
                self.assertTrue(cloner.status()['copy_complete'])
                commands.assert_not_called()
                with self.assertRaisesRegex(ValueError, 'already running'):
                    cloner.scan('usb')
            else:
                self.assertEqual(seconds, 3)
                self.assertEqual(cloner.status()['phase'], 'rebooting')
        with patch.object(host.Path, 'stat', side_effect=[MagicMock(), MagicMock(), FileNotFoundError()]) as stat, \
             patch.object(host.time, 'sleep', side_effect=waiting) as sleep, \
             patch.object(host, 'run') as commands:
            cloner.restart_after_removal('/dev/sdb')
        self.assertEqual(stat.call_count, 3)
        self.assertEqual([c.args for c in sleep.call_args_list], [(2,), (2,), (3,)])
        commands.assert_called_once_with('systemctl', 'reboot', '--no-block')
        self.assertEqual(cloner.status()['status'], 'running')

    def test_removal_check_error_never_reboots_and_reboot_error_keeps_writes_blocked(self):
        for error in [PermissionError('cannot inspect device'), FileNotFoundError()]:
            with self.subTest(error=type(error).__name__):
                cloner = host.Cloner()
                with patch.object(host.Path, 'stat', side_effect=error), \
                     patch.object(host.time, 'sleep'), \
                     patch.object(host, 'run', side_effect=ValueError('reboot rejected')) as commands:
                    cloner.restart_after_removal('/dev/sdb')
                if isinstance(error, PermissionError):
                    commands.assert_not_called()
                else:
                    commands.assert_called_once()
                self.assertEqual(cloner.status()['phase'], 'reboot_failed')
                self.assertEqual(cloner.status()['status'], 'running')
                self.assertTrue(cloner.status()['copy_complete'])
                self.assertIn('restart the Library manually', cloner.status()['message'])

    def test_helper_restart_after_copy_keeps_writes_blocked_until_manual_reboot(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'status.json'
            state.write_text(json.dumps({'status': 'running', 'copy_complete': True,
                                         'phase': 'awaiting_removal', 'destination': '/dev/sdb'}))
            cloner = host.Cloner(state)
            self.assertEqual(cloner.status()['status'], 'running')
            self.assertEqual(cloner.status()['phase'], 'reboot_failed')
            self.assertIn('Remove the destination', cloner.status()['message'])


class CopyProgressTests(unittest.TestCase):
    def test_final_counter_is_published_even_when_progress_is_throttled(self):
        process = MagicMock()
        process.stdout = io.StringIO('  1,024  50% 1MB/s\n  2,048 100% 1MB/s\n')
        process.wait.return_value = 0
        update = MagicMock()
        with patch.object(host.subprocess, 'Popen') as popen, patch.object(host.time, 'monotonic', return_value=10):
            popen.return_value.__enter__.return_value = process
            host.copy_files(['-rtx', '/source/', '/destination/'], update)
        self.assertEqual([c.kwargs['copied'] for c in update.call_args_list], [1024, 2048])

    def test_failed_copy_does_not_publish_a_successful_final_counter(self):
        process = MagicMock()
        process.stdout = io.StringIO('  1,024  50% 1MB/s\n')
        process.wait.return_value = 1
        update = MagicMock()
        with patch.object(host.subprocess, 'Popen') as popen, patch.object(host.time, 'monotonic', return_value=10):
            popen.return_value.__enter__.return_value = process
            with self.assertRaisesRegex(ValueError, 'Copy failed'):
                host.copy_files(['-rtx', '/source/', '/destination/'], update)
        update.assert_called_once_with(copied=1024)


class AppCloneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = app.Application(app.Storage(self.tmp.name, require_mount=False, reserve=0))
        self.app.internet = {'status': 'online'}

    def test_active_clone_blocks_upload_download_restart_and_refresh(self):
        with patch.object(app, 'clone_status', return_value={'status': 'running'}), patch.object(app, 'request_host_restart') as restart:
            for action in [lambda: self.app.upload(io.BytesIO(b'a'), 1, 'music', 'x'),
                           lambda: self.app.enqueue(['x']), self.app.restart]:
                with self.assertRaisesRegex(ValueError, 'clone'):
                    action()
            self.app.refresh()
            self.assertFalse(self.app.refreshing)
            restart.assert_not_called()

    def test_upload_jobs_and_refresh_block_clone_admission(self):
        with patch.object(app, 'clone_status', return_value={'status': 'idle'}), patch.object(app, 'clone_request') as request:
            for status in app.ACTIVE:
                self.app.jobs = {'test': {'status': status}}
                with self.assertRaisesRegex(ValueError, 'Wait for'):
                    self.app.clone('start', {})
            self.app.jobs = {}
            for attr in ('upload_active', 'refreshing'):
                setattr(self.app, attr, True)
                with self.assertRaisesRegex(ValueError, 'Wait for'):
                    self.app.clone('start', {})
                setattr(self.app, attr, False)
            request.assert_not_called()
            self.app.clone('start', {'token': 't', 'confirmation': '/dev/sdb'})
            request.assert_called_once_with('start', token='t', confirmation='/dev/sdb', sd_confirmed=False)

    def test_unknown_service_state_fails_closed_but_absent_service_allows_downloads(self):
        with patch.object(app, 'clone_status', return_value={'status': 'unknown'}):
            with self.assertRaises(ValueError): app.check_clone_idle()
        with patch.object(app, 'CLONE_SOCKET', self.tmp.name + '/missing'):
            self.assertFalse(app.clone_status()['available'])
            app.check_clone_idle()


class BootRewriteTests(unittest.TestCase):
    def test_rewrites_only_boot_and_root_mounts_and_keeps_cmdline_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'etc').mkdir()
            (root / 'boot/firmware').mkdir(parents=True)
            (root / 'etc/fstab').write_text('PARTUUID=old-02 / ext4 defaults 0 1\nLABEL=bootfs /boot/firmware vfat defaults 0 2\nLABEL=Library_USB /Library exfat defaults 0 0\n')
            (root / 'boot/firmware/cmdline.txt').write_text('console=tty1 root=PARTUUID=old-02 rootwait quiet\n')
            info = {'root': {'name': '/dev/mmcblk0p2', 'partuuid': 'old-02'},
                    'boot': {'name': '/dev/mmcblk0p1', 'label': 'bootfs'}}
            with patch.object(host, 'run', side_effect=lambda *a, **k: 'new-' + a[-1][-1]):
                host.rewrite_boot(root, info, '/dev/sdb2', '/dev/sdb1')
            self.assertEqual((root / 'etc/fstab').read_text(), 'UUID=new-2 / ext4 defaults 0 1\nUUID=new-1 /boot/firmware vfat defaults 0 2\nLABEL=Library_USB /Library exfat defaults 0 0\n')
            self.assertEqual((root / 'boot/firmware/cmdline.txt').read_text(), 'console=tty1 root=PARTUUID=new-2 rootwait quiet\n')


if __name__ == '__main__':
    unittest.main()
