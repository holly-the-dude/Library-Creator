"""Offline checks for download navigation and startup wiring.

Run from the repository root with:
python3 -m unittest discover -s setup_library/tests -p test_download_navigation.py -v
No appliance services or library content are touched.
"""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests
import yaml

FILES = Path(__file__).resolve().parents[1] / "files"
WEB = FILES / "containers/webserver"
spec = importlib.util.spec_from_file_location("library_web", WEB / "library.py")
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)


class DownloadNavigationTests(unittest.TestCase):
    def setUp(self):
        self.config = yaml.safe_load((WEB / "library_setup.yml").read_text())
        self.service = next(s for s in self.config["services"] if s["name"] == "data_download")

    def test_downloads_follows_meshtastic_before_shutdown_when_offline(self):
        def response(url, **kwargs):
            # The downloader health response does not depend on internet access.
            return Mock(content=b'{"status": "ok"}' if url.endswith("/api/health") else b"<html")

        with patch.object(web.requests, "get", side_effect=response) as get:
            links = web.discover_services(self.config["services"])
        html = web.get_html_template("\n".join(links), "http://10.1.1.1:9999")
        self.assertLess(html.index(">Meshtastic</a>"), html.index(">Downloads</a>"))
        self.assertLess(html.index(">Downloads</a>"), html.index(">Shutdown</a>"))
        self.assertIn('href="http://10.1.1.1:4826"', html)
        get.assert_any_call("http://10.1.1.1:4826/api/health", timeout=5)

    def test_unavailable_downloader_is_omitted(self):
        with patch.object(web.requests, "get", side_effect=requests.ConnectionError):
            self.assertEqual(web.check_service(self.service), "")

    def test_new_navigation_updates_existing_index_and_category_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library, pages = root / "library", root / "web"
            (library / "Books").mkdir(parents=True)
            (library / "Books/example.pdf").write_bytes(b"example")
            pages.mkdir()
            old = web.get_html_template("", "http://10.1.1.1:9999")
            (pages / "index.html").write_text(old.replace(web.TREE_CONTENT_PLACEHOLDER, ""))
            (pages / "file_count.txt").write_text("1")
            self.config["webserver"].update(library_path=str(library), web_path=str(pages))
            with patch.object(web, "load_config", return_value=self.config), \
                 patch.object(web, "configure_nginx"), \
                 patch.object(web.requests, "get", return_value=Mock(content=b'{"status": "ok"}')):
                web.main()
            for filename in ("index.html", "Books.html"):
                self.assertIn('href="http://10.1.1.1:4826"', (pages / filename).read_text())



if __name__ == "__main__":
    unittest.main()
