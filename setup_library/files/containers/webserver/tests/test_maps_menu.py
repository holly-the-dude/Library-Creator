import sys
from pathlib import Path
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import library


class MapMenuTests(unittest.TestCase):
    def setUp(self):
        self.services = library.DEFAULT_CONFIG['services']

    def test_one_maps_button_offers_two_available_viewers(self):
        with patch.object(library, 'check_service', return_value='<a>available</a>'):
            links = library.discover_services(self.services)
        menu = next(link for link in links if 'maps-menu' in link)
        self.assertEqual(menu.count('<summary>Maps</summary>'), 1)
        self.assertIn('/services/8080/', menu)
        self.assertIn('/services/8093/', menu)
        self.assertIn('OpenStreetMap', menu)
        self.assertIn('StreetZim', menu)
        self.assertEqual(len(links), 4)

    def test_streetzim_only_and_unavailable_viewer(self):
        with patch.object(library, 'check_service', side_effect=lambda s: 'up' if s['name'] == 'street_zim' else ''):
            links = library.discover_services(self.services)
        self.assertEqual(len(links), 2)  # Music and Maps remain available as menus.
        menu = next(link for link in links if 'maps-menu' in link)
        self.assertIn('/services/8093/', menu)
        self.assertNotIn('/services/8080/', menu)
        self.assertIn('Not running', menu)

    def test_unhealthy_response_cannot_offer_a_broken_service(self):
        service = next(s for s in self.services if s['name'] == 'street_zim')
        with patch.object(library.requests, 'get', return_value=Mock(status_code=503, content=b'{"ready": true}')):
            self.assertEqual(library.check_service(service), '')


if __name__ == '__main__':
    unittest.main()
