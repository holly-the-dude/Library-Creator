import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import library


class MusicMenuTests(unittest.TestCase):
    def setUp(self):
        self.services = yaml.safe_load(Path(library.__file__).with_name('library_setup.yml').read_text())['services']

    def menu(self, available):
        with patch.object(library, 'check_service', side_effect=lambda s: 'up' if s['name'] in available else ''):
            links = library.discover_services(self.services)
        self.assertEqual(sum('music-menu' in link for link in links), 1)
        return next(link for link in links if 'music-menu' in link)

    def test_both_players_keep_lms_proxy_and_ipod_port(self):
        menu = self.menu({'music', 'music_player'})
        self.assertIn('<summary>Music</summary>', menu)
        self.assertIn('href="/music"', menu)
        self.assertIn('href="/services/2001/"', menu)
        self.assertIn('Music library (LMS)', menu)
        self.assertIn('iPod-style player', menu)
        self.assertNotIn('Not running', menu)

    def test_either_player_can_run_independently(self):
        for active, present, absent in [('music', '/music', '/services/2001/'),
                                        ('music_player', '/services/2001/', '/music')]:
            with self.subTest(active=active):
                menu = self.menu({active})
                self.assertIn(f'href="{present}"', menu)
                self.assertNotIn(f'href="{absent}"', menu)
                self.assertEqual(menu.count('Not running'), 1)

    def test_lms_probe_uses_its_deployed_music_path(self):
        service = next(s for s in self.services if s['name'] == 'music')
        with patch.object(library.requests, 'get', return_value=Mock(status_code=200, content=b'LMS')) as get:
            self.assertIn('href="/music"', library.check_service(service))
        self.assertEqual(get.call_args.args[0], 'http://10.88.0.210:5082/music')


if __name__ == '__main__':
    unittest.main()
