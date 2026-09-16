import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from open_sprinkler.auth import BrowserSessionManager


class BrowserSessionTests(unittest.TestCase):
    def test_signed_session_round_trips_until_expiry(self):
        manager = BrowserSessionManager("a" * 32, lifetime_seconds=600)
        session = manager.issue(now_epoch=1_000)

        self.assertEqual(
            manager.verify(session.value, now_epoch=1_599), session.csrf_token
        )
        self.assertIsNone(manager.verify(session.value, now_epoch=1_600))

    def test_tampered_session_is_rejected(self):
        manager = BrowserSessionManager("a" * 32)
        session = manager.issue(now_epoch=1_000)
        tampered = session.value.replace(session.csrf_token, "forged")

        self.assertIsNone(manager.verify(tampered, now_epoch=1_001))
