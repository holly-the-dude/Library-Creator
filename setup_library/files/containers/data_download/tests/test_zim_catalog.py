"""Offline OPDS coverage, including map archives and paginated failures."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sources


def feed(entries, total=1, start=0):
    return f'''<feed xmlns="http://www.w3.org/2005/Atom">
    <totalResults>{total}</totalResults><startIndex>{start}</startIndex>
    {entries}</feed>'''


def entry(url="https://lb.download.kiwix.org/zim/maps/maps_en_fiji_2026-06.zim.meta4",
          size="160348160", extra=""):
    return f'''<entry><title>Fiji &amp; islands</title>
    <summary>Full map, including roads and landmarks</summary>
    <language>eng,fra</language><category/><tags>_sw:no;_pictures:yes</tags>
    <updated>2026-06-01T00:00:00Z</updated>{extra}
    <link type="text/html" href="https://example.org/preview"/>
    <link type="application/x-zim" href="{url}" length="{size}"/>
    </entry>'''


class ZimCatalogTests(unittest.TestCase):
    def test_map_metadata_and_metalink_resolve_to_real_zim(self):
        rows, count, total, start = sources.parse_zim_catalog(feed(entry()))
        self.assertEqual((count, total, start), (1, 1, 0))
        row = rows[0]
        self.assertEqual(row["title"], "Fiji & islands")
        self.assertEqual(row["description"], "Full map, including roads and landmarks")
        self.assertEqual(row["category"], "maps")
        self.assertEqual(row["languages"], ["eng", "fra"])
        self.assertEqual(row["size"], 160348160)  # OPDS length is already bytes.
        self.assertTrue(row["size_is_approximate"])
        self.assertEqual(row["date"], "2026-06-01")
        self.assertTrue(row["url"].endswith(".zim"))
        self.assertEqual(row["destination"], "wiki/maps_en_fiji_2026-06.zim")

    def test_direct_zim_link_and_flavour(self):
        xml = feed(entry("https://download.kiwix.org/zim/wikipedia/wikipedia_en_all_nopic_2026-06.zim",
                         extra="<flavour>nopic</flavour>"))
        row = sources.parse_zim_catalog(xml)[0][0]
        self.assertEqual(row["flavour"], "nopic")
        self.assertEqual(row["category"], "wikipedia")

    def test_rejects_unsafe_links_and_bad_lengths(self):
        for url in ["http://download.kiwix.org/zim/maps/a.zim", "https://evil.example/zim/maps/a.zim",
                    "https://download.kiwix.org.evil.example/zim/maps/a.zim",
                    "https://download.kiwix.org/zim/maps/%2e%2e%2ffile.zim",
                    "https://user@download.kiwix.org/zim/maps/a.zim",
                    "https://download.kiwix.org/zim/maps/a.zim.torrent"]:
            with self.subTest(url=url):
                self.assertEqual(sources.parse_zim_catalog(feed(entry(url)))[0], [])
        for size in ["", "unknown", "0", "-1"]:
            with self.subTest(size=size):
                self.assertEqual(sources.parse_zim_catalog(feed(entry(size=size)))[0], [])

    def test_pages_use_actual_entry_count_and_preserve_non_wikipedia(self):
        published = []
        with patch.object(sources, "fetch", side_effect=[feed(entry(), 2), feed(entry(), 2, 1)]) as fetch:
            self.assertEqual(sources.discover("wiki", published.extend), "")
        self.assertEqual(len(published), 2)
        self.assertEqual(fetch.call_args_list[1].args[0], sources.ZIM_CATALOG_URL + "?count=500&start=1")

    def test_incomplete_or_repeated_page_fails_without_losing_published_rows(self):
        for second in [feed("", 2, 1), feed(entry(), 2, 0), "<html>unavailable</html>"]:
            published = []
            with self.subTest(second=second), patch.object(sources, "fetch", side_effect=[feed(entry(), 2), second]):
                with self.assertRaises(ValueError):
                    sources.discover("wiki", published.extend)
                self.assertEqual(len(published), 1)

    def test_no_results_and_missing_pagination(self):
        self.assertEqual(sources.parse_zim_catalog(feed("", 0)), ([], 0, 0, 0))
        with self.assertRaises(ValueError):
            sources.parse_zim_catalog('<feed xmlns="http://www.w3.org/2005/Atom"/>')

    def test_resolves_real_us_map_size_for_old_cached_rows(self):
        row = sources.item("wiki", "https://lb.download.kiwix.org/zim/maps/maps_en_united-states-of-america_2026-06.zim",
                           16601606144)
        digest = "cfc169f5722ef68694d738eaa07f77eebd2dcc087148ff11b05bad435e0fa7e0"
        xml = f'''<metalink xmlns="urn:ietf:params:xml:ns:metalink">
          <file name="{row['filename']}"><size>16601605855</size>
          <hash type="sha-256">{digest}</hash></file></metalink>'''
        with patch.object(sources, "fetch", return_value=xml) as fetch:
            sources.resolve_zim_metadata(row)
        fetch.assert_called_once_with(row["url"] + ".meta4")
        self.assertEqual(row["size"], 16601605855)
        self.assertEqual(row["sha256"], digest)
        self.assertFalse(row["size_is_approximate"])

    def test_invalid_metalink_cannot_change_queued_size(self):
        row = sources.item("wiki", "https://download.kiwix.org/zim/maps/test.zim", 1024)
        valid = '''<metalink xmlns="urn:ietf:params:xml:ns:metalink"><file name="test.zim">
          <size>1025</size><hash type="sha-256">''' + "a" * 64 + '''</hash></file></metalink>'''
        for xml in [valid.replace('test.zim', 'other.zim'), valid.replace('1025', '-1'),
                    valid.replace('1025', 'unknown'), valid.replace('sha-256', 'sha-1'),
                    valid.replace('a' * 64, 'bad-checksum'), '<html/>']:
            with self.subTest(xml=xml), patch.object(sources, "fetch", return_value=xml):
                with self.assertRaises(ValueError):
                    sources.resolve_zim_metadata(row)
                self.assertEqual(row["size"], 1024)
                self.assertIsNone(row["sha256"])

    def test_non_kiwix_downloads_do_not_fetch_metalink(self):
        with patch.object(sources, "fetch") as fetch:
            for source, url in [("maps", "https://example.org/map.pmtiles"),
                                ("wiki", "https://dumps.wikimedia.org/kiwix/zim/wikipedia/test.zim")]:
                sources.resolve_zim_metadata(sources.item(source, url, 1234))
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
