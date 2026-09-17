import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from open_sprinkler.config import load_settings, read_api_token


class ConfigTests(unittest.TestCase):
    def test_loads_named_stations_and_private_server_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "open-sprinkler.ini"
            config_path.write_text(
                "[Station GPIOs]\npins = 5, 6\nnames = Front, Back\n",
                encoding="utf-8",
            )

            settings = load_settings(config_path)

        self.assertEqual([station.id for station in settings.stations], [1, 2])
        self.assertEqual(
            [station.name for station in settings.stations], ["Front", "Back"]
        )
        self.assertEqual([station.pin for station in settings.stations], [5, 6])
        self.assertEqual(settings.listen_host, "127.0.0.1")
        self.assertEqual(settings.listen_port, 8000)
        self.assertTrue(settings.secure_cookies)
        self.assertEqual(settings.max_duration_seconds, 7_200)
        self.assertEqual(settings.timezone, "UTC")
        self.assertEqual(settings.scheduler_poll_seconds, 15)
        self.assertEqual(settings.scheduler_grace_seconds, 300)
        self.assertEqual(settings.weather_poll_seconds, 900)
        self.assertEqual(
            settings.database_path,
            Path("/var/lib/open-sprinkler/open-sprinkler.db"),
        )

    def test_station_names_must_match_pin_count(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "open-sprinkler.ini"
            config_path.write_text(
                "[Station GPIOs]\npins = 5, 6\nnames = Front\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "must match"):
                load_settings(config_path)

    def test_api_token_must_be_long_enough(self):
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "api-token"
            token_path.write_text("too-short\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "at least 32 characters"):
                read_api_token(token_path)
