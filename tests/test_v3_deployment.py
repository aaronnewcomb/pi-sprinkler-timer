import configparser
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class DeploymentTests(unittest.TestCase):
    def test_service_uses_dedicated_account_and_managed_directories(self):
        unit = (ROOT / "systemd" / "open-sprinkler-v3.service").read_text(
            encoding="utf-8"
        )

        self.assertIn("User=open-sprinkler", unit)
        self.assertIn("SupplementaryGroups=gpio", unit)
        self.assertIn("RuntimeDirectory=open-sprinkler", unit)
        self.assertIn("StateDirectory=open-sprinkler", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("/opt/open-sprinkler/.venv/bin/open-sprinkler-v3", unit)

    def test_lighttpd_proxies_only_to_loopback_application_port(self):
        proxy = (ROOT / "lighttpd" / "99-open-sprinkler-v3.conf").read_text(
            encoding="utf-8"
        )

        self.assertIn('"host" => "127.0.0.1"', proxy)
        self.assertIn('"port" => 8000', proxy)
        self.assertIn('"/" => (', proxy)
        self.assertNotIn('"" => (', proxy)
        self.assertNotIn("0.0.0.0", proxy)

    def test_tls_example_redirects_plain_http(self):
        tls = (ROOT / "lighttpd" / "98-open-sprinkler-tls.conf.example").read_text(
            encoding="utf-8"
        )

        self.assertIn('"mod_redirect"', tls)
        self.assertIn('$HTTP["scheme"] == "http"', tls)
        self.assertIn('url.redirect = ("" => "https://', tls)

    def test_example_enables_secure_browser_cookies(self):
        parser = configparser.ConfigParser()
        parser.read(ROOT / "open-sprinkler-v3.ini.example")

        self.assertTrue(parser.getboolean("Server", "secure_cookies"))

    def test_schedule_duration_survives_form_reset(self):
        script = (
            ROOT / "src" / "open_sprinkler" / "web" / "assets" / "app.js"
        ).read_text(encoding="utf-8")

        self.assertIn('duration.defaultValue = "10"', script)

    def test_dashboard_explains_connection_and_rain_delay_behavior(self):
        web_root = ROOT / "src" / "open_sprinkler" / "web"
        page = (web_root / "index.html").read_text(encoding="utf-8")
        script = (web_root / "assets" / "app.js").read_text(encoding="utf-8")

        self.assertIn("Pi Sprinkler Timer", page)
        self.assertIn('id="settings-dialog"', page)
        self.assertIn("Weather automation manages a separate automatic hold", page)
        self.assertIn(
            'id="stop-all-button" class="button danger" type="button" hidden', page
        )
        self.assertIn("elements.stopAllButton.hidden = !active", script)
        self.assertIn("Controller online", script)
        self.assertIn("data-countdown-until", script)
        self.assertIn('id="custom-delay-hours"', page)
        self.assertIn('id="weather-form"', page)
        self.assertIn("Manual and weather holds", script)

    def test_installation_guide_has_complete_tls_paths(self):
        guide = (ROOT / "docs" / "V3_INSTALLATION.md").read_text(encoding="utf-8")

        self.assertIn("sudo apt install -y git ca-certificates", guide)
        self.assertIn("Option A: temporary HTTP", guide)
        self.assertIn("secure_cookies = false", guide)
        self.assertIn("Option B: trusted HTTPS", guide)
        self.assertIn("sudo apt install mkcert", guide)
        self.assertIn("98-open-sprinkler-tls.conf", guide)
        self.assertIn("rootCA.pem", guide)
        self.assertIn("Never copy or share `rootCA-key.pem`", guide)
        self.assertIn("api.open-meteo.com", guide)
        self.assertIn("live\ncountdown", guide)

    def test_home_assistant_uses_product_namespace(self):
        configuration = (
            ROOT / "docs" / "home-assistant" / "rest.yaml"
        ).read_text(encoding="utf-8")

        self.assertIn("PI_SPRINKLER_HOST", configuration)
        self.assertIn("pi_sprinkler_authorization", configuration)
        self.assertIn("pi_sprinkler_active_station", configuration)
        self.assertIn("pi_sprinkler_start_station", configuration)
        self.assertIn("pi_sprinkler_stop_station", configuration)
        self.assertIn("pi_sprinkler_stop_all", configuration)
        self.assertNotIn("OPEN_SPRINKLER_HOST", configuration)
        self.assertNotIn("open_sprinkler_", configuration)
