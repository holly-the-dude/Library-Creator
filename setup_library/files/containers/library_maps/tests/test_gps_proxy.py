import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from configure_gps import gps_proxy_directive


class GPSProxyTests(unittest.TestCase):
    def test_default_and_shared_feed(self):
        self.assertEqual(gps_proxy_directive(''), 'proxy_pass http://127.0.0.1:8765/api/gps;\n')
        self.assertEqual(gps_proxy_directive('http://10.88.0.216:8093/'),
                         'proxy_pass http://10.88.0.216:8093/api/gps;\n')

    def test_reject_configuration_injection_or_wrong_origin(self):
        for origin in ['http://host;bad', 'http://host\n', 'http://user@host',
                       'http://host/api/gps', 'http://host:99999', 'http://$host']:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                gps_proxy_directive(origin)
