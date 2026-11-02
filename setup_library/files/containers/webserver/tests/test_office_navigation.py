import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, mock_open, patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import library


class OfficeNavigationTests(unittest.TestCase):
    def setUp(self):
        self.config = yaml.safe_load(Path(library.__file__).with_name('library_setup.yml').read_text())

    def test_office_redirect_uses_https_without_changing_other_services(self):
        output = mock_open()
        with patch('builtins.open', output), patch.object(library.os, 'system', return_value=0):
            library.configure_nginx(self.config['webserver'], self.config['services'])
        config = output().write.call_args.args[0]
        self.assertIn('return 302 https://$host:3001/;', config)
        self.assertIn('return 302 $scheme://$host:2001/;', config)
        self.assertIn('return 302 $scheme://$host:9999/;', config)

    def test_office_is_discovered_on_internal_selkies_port(self):
        service = next(s for s in self.config['services'] if s['name'] == 'craft_apps')
        with patch.object(library.requests, 'get', return_value=Mock(status_code=200, content=b'<title>Selkies</title>')) as get:
            link = library.check_service(service)
        get.assert_called_once_with('http://10.88.0.218:3000', timeout=5)
        self.assertIn('href="/services/3001/"', link)
        self.assertIn('>Office</a>', link)

    def test_stopped_office_is_omitted_from_navigation(self):
        service = next(s for s in self.config['services'] if s['name'] == 'craft_apps')
        for response in (Mock(status_code=503, content=b'Selkies'),
                         Mock(status_code=200, content=b'unrelated service')):
            with patch.object(library.requests, 'get', return_value=response):
                self.assertEqual(library.check_service(service), '')
        with patch.object(library.requests, 'get', side_effect=library.requests.ConnectionError):
            self.assertEqual(library.check_service(service), '')

    def test_invalid_scheme_cannot_enter_nginx_config(self):
        with self.assertRaises(ValueError):
            library.configure_nginx({}, [{'external_port': 3001, 'external_scheme': 'https;'}])


if __name__ == '__main__':
    unittest.main()
