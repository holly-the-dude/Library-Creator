"""StreetZim catalog and exact-size/checksum transfer tests; no network."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import sources
from test_downloader import Response

URL = 'https://archive.org/download/streetzim-colorado/osm-colorado-2026-10-25.zim'


def card(url=URL):
    return f'''<div class="map-card"><div class="map-card-head">
      <div class="map-card-title">Colorado &amp; mountains</div>
      <div class="map-card-size">841 MB</div></div>
      <time datetime="2026-10-25">25 Oct</time>
      <p class="map-card-desc">Roads and <strong>places</strong></p>
      <span class="map-badge badge-nav">Routing &amp; Directions</span>
      <div class="map-card-links"><a href="{url}">Download</a>
      <a href="/drive/?zim={url}">Preview</a><a href="/torrents/colorado.torrent">Torrent</a></div></div>'''


def metadata(body, name='osm-colorado-2026-10-25.zim'):
    return json.dumps({'files': [{'name': name, 'size': str(len(body)),
                                  'md5': hashlib.md5(body).hexdigest()}]})


class StreetZimTests(unittest.TestCase):
    def test_cards_preserve_metadata_and_deduplicate_links(self):
        rows = sources.parse_streetzim_catalog(card() + card())
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['title'], 'Colorado & mountains')
        self.assertEqual(row['description'], 'Roads and places')
        self.assertEqual(row['features'], 'Routing & Directions')
        self.assertEqual(row['date'], '2026-10-25')
        self.assertEqual(row['destination'], 'wiki/osm-colorado-2026-10-25.zim')
        self.assertTrue(row['size_is_approximate'])
        self.assertEqual(row['size'], 841 * 1024 ** 2)

    def test_rejects_preview_foreign_and_unsafe_download_urls(self):
        for url in ['http://archive.org/download/streetzim-colorado/a.zim',
                    'https://archive.org.evil.test/download/streetzim-colorado/a.zim',
                    'https://user@archive.org/download/streetzim-colorado/a.zim',
                    'https://archive.org/download/unrelated/a.zim',
                    'https://archive.org/download/streetzim-colorado/%2e%2e%2fa.zim',
                    'https://archive.org/download/streetzim-colorado/._a.zim',
                    URL + '?download=1', URL + '.torrent']:
            with self.subTest(url=url):
                self.assertEqual(sources.parse_streetzim_catalog(card(url)), [])

    def test_discovery_and_empty_catalog_failure(self):
        rows = []
        with patch.object(sources, 'fetch', return_value=card()) as fetch:
            self.assertEqual(sources.discover('streetzim', rows.extend), '')
            fetch.assert_called_once_with(sources.STREETZIM_URL)
        self.assertEqual(len(rows), 1)
        with patch.object(sources, 'fetch', return_value='<html>maintenance</html>'):
            with self.assertRaisesRegex(ValueError, 'No StreetZim'):
                sources.discover('streetzim', rows.extend)

    def test_metadata_requires_exact_selected_file_and_valid_checksum(self):
        row = sources.parse_streetzim_catalog(card())[0]
        original = dict(row)
        for data in [metadata(b'data', 'other.zim'), metadata(b'data').replace('"4"', '"0"'),
                     metadata(b'data').replace(hashlib.md5(b'data').hexdigest(), 'invalid')]:
            with patch.object(sources, 'fetch', return_value=data), self.assertRaises(ValueError):
                sources.resolve_zim_metadata(row)
            self.assertEqual(row, original)

    def test_stream_uses_exact_metadata_and_verifies_zim_and_md5(self):
        body = b'ZIM\x04' + b'archive fixture' * 20
        row = sources.parse_streetzim_catalog(card())[0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'download.part'
            storage = app.Storage(Path(directory), require_mount=False, reserve=0)
            event = threading.Event()
            with patch.object(sources, 'fetch', return_value=metadata(body)) as fetch, \
                 patch.object(sources, 'open_url', return_value=Response(body, headers={'Content-Length': str(len(body))})):
                app.stream_download(row, path, storage, event, lambda **kwargs: None)
            fetch.assert_called_once_with('https://archive.org/metadata/streetzim-colorado')
            self.assertEqual(path.read_bytes(), body)
            self.assertEqual(row['size'], len(body))
            self.assertFalse(row['size_is_approximate'])
            app.verify(row, path, event)
            self.assertEqual(row['sha256'], hashlib.sha256(body).hexdigest())
            path.write_bytes(body[:-1] + b'x')
            with self.assertRaisesRegex(ValueError, 'MD5 mismatch'):
                app.verify(row, path, event)
            path.write_bytes(b'HTML' + body[4:])
            with self.assertRaisesRegex(ValueError, 'ZIM file'):
                app.verify(row, path, event)


if __name__ == '__main__':
    unittest.main()
