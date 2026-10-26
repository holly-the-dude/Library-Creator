import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import gps_upstream, make_library


class ConfigurationTests(unittest.TestCase):
    def test_sources(self):
        self.assertEqual(gps_upstream({}), ('relay', 'http://10.88.0.212:8080'))
        self.assertEqual(gps_upstream({'GPS_MODE': 'serial'}), ('serial', 'http://127.0.0.1:8765'))

    def test_reject_nginx_directives_credentials_and_non_origins(self):
        for value in ['http://host;foo', 'http://host/other', 'http://host\n',
                      'https://host', 'http://user:pass@host', 'http://host?x',
                      'http://host:99999', 'http://$host']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                gps_upstream({'GPS_UPSTREAM': value})

    def test_catalog_is_private_and_handles_spaces_without_a_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'city map.zim').write_bytes(b'example')
            (root / 'incomplete.zim.part').write_bytes(b'partial')
            library = root / 'library.xml'
            with patch('server.subprocess.run') as run:
                archives = make_library(root, library)
            self.assertEqual([p.name for p in archives], ['city map.zim'])
            run.assert_called_once_with(['kiwix-manage', str(library), 'add', str(root / 'city map.zim')], check=True)
            self.assertIn('<library', library.read_text())

    def test_empty_library_still_has_a_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('server.subprocess.run') as run:
                self.assertEqual(make_library(root, root / 'library.xml'), [])
                run.assert_not_called()

    def test_macos_sidecars_are_ignored_without_changing_the_usb_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'osm-colorado-2026-10-25.zim'
            archive.write_bytes(b'archive fixture')
            sidecars = [root / ('._' + archive.name), root / '._orphan.zim']
            for sidecar in sidecars:
                sidecar.write_bytes(b'AppleDouble metadata fixture')
            library = root / 'library.xml'
            with patch('server.subprocess.run') as run:
                self.assertEqual(make_library(root, library), [archive])
            run.assert_called_once_with(
                ['kiwix-manage', str(library), 'add', str(archive)], check=True)
            for sidecar in sidecars:
                self.assertEqual(sidecar.read_bytes(), b'AppleDouble metadata fixture')

    def test_folder_with_only_sidecars_produces_an_empty_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '._osm-colorado-2026-10-25.zim').write_bytes(b'metadata')
            with patch('server.subprocess.run') as run:
                self.assertEqual(make_library(root, root / 'library.xml'), [])
                run.assert_not_called()

    def test_invalid_real_archive_still_reports_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'broken.zim').write_bytes(b'not a ZIM')
            with patch('server.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'kiwix-manage')):
                with self.assertRaises(subprocess.CalledProcessError):
                    make_library(root, root / 'library.xml')


if __name__ == '__main__':
    unittest.main()
