import asyncio
import sys
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pi_sprinkler.persistence import SQLiteRepository
from pi_sprinkler.weather import (
    DailyForecast,
    HourlyPrecipitation,
    ResolvedLocation,
    WeatherAutomation,
    WeatherSettings,
    WeatherSnapshot,
)


class FakeWeatherProvider:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.resolved = []
        self.forecasts = []

    async def resolve_location(self, postal_code):
        self.resolved.append(postal_code)
        return ResolvedLocation(37.323, -122.0322, "Cupertino, California, US")

    async def forecast(self, latitude, longitude):
        self.forecasts.append((latitude, longitude))
        return self.snapshot


def weather_snapshot(now):
    return WeatherSnapshot(
        observed_at=now,
        temperature_f=68.5,
        weather_code=61,
        precipitation_inches=0.04,
        hourly_precipitation=(
            HourlyPrecipitation(now - timedelta(hours=2), 0.12),
            HourlyPrecipitation(now + timedelta(hours=1), 0.18),
            HourlyPrecipitation(now + timedelta(hours=2), 0.05),
        ),
        daily=(
            DailyForecast(date(2026, 9, 16), 61, 70, 55, 0.35, 80),
            DailyForecast(date(2026, 9, 17), 2, 73, 54, 0.01, 20),
        ),
    )


class WeatherAutomationTests(unittest.TestCase):
    def setUp(self):
        self.repository = SQLiteRepository.open(":memory:")
        self.repository.initialize()

    def tearDown(self):
        self.repository.close()

    def test_postal_code_is_resolved_and_precipitation_sets_weather_hold(self):
        now = datetime.now(UTC)
        provider = FakeWeatherProvider(weather_snapshot(now))
        automation = WeatherAutomation(self.repository, provider=provider)

        status = asyncio.run(
            automation.configure(
                WeatherSettings(
                    enabled=True,
                    postal_code="95014",
                    precipitation_threshold_inches=0.25,
                    delay_hours_after_precipitation=24,
                )
            )
        )

        self.assertEqual(provider.resolved, ["95014"])
        self.assertEqual(provider.forecasts, [(37.323, -122.0322)])
        self.assertEqual(status.settings.location_name, "Cupertino, California, US")
        self.assertAlmostEqual(status.evaluated_precipitation_inches, 0.35)
        self.assertIsNotNone(status.automatic_hold_until)
        self.assertGreater(status.automatic_hold_until, now + timedelta(hours=25))

    def test_manual_and_weather_holds_remain_independent(self):
        now = datetime.now(UTC)
        self.repository.set_manual_rain_delay(now + timedelta(hours=12))
        self.repository.set_weather_rain_delay(now + timedelta(hours=30))

        self.assertEqual(self.repository.get_rain_delay(), now + timedelta(hours=30))
        self.repository.set_manual_rain_delay(None)
        self.assertEqual(self.repository.get_rain_delay(), now + timedelta(hours=30))

    def test_disabling_weather_clears_only_automatic_hold(self):
        now = datetime.now(UTC)
        provider = FakeWeatherProvider(weather_snapshot(now))
        automation = WeatherAutomation(self.repository, provider=provider)
        self.repository.set_manual_rain_delay(now + timedelta(hours=10))
        self.repository.set_weather_rain_delay(now + timedelta(hours=20))

        asyncio.run(automation.configure(WeatherSettings(enabled=False)))

        self.assertIsNone(self.repository.get_weather_rain_delay())
        self.assertEqual(
            self.repository.get_manual_rain_delay(), now + timedelta(hours=10)
        )

    def test_subthreshold_precipitation_does_not_set_hold(self):
        now = datetime.now(UTC)
        provider = FakeWeatherProvider(weather_snapshot(now))
        automation = WeatherAutomation(self.repository, provider=provider)

        status = asyncio.run(
            automation.configure(
                WeatherSettings(
                    enabled=True,
                    latitude=37.323,
                    longitude=-122.0322,
                    precipitation_threshold_inches=1,
                    delay_hours_after_precipitation=24,
                )
            )
        )

        self.assertIsNone(status.automatic_hold_until)

    def test_persisted_settings_refresh_before_background_polling(self):
        now = datetime.now(UTC)
        provider = FakeWeatherProvider(weather_snapshot(now))
        first = WeatherAutomation(self.repository, provider=provider)
        asyncio.run(
            first.configure(
                WeatherSettings(
                    enabled=True,
                    latitude=37.323,
                    longitude=-122.0322,
                    precipitation_threshold_inches=0.25,
                    delay_hours_after_precipitation=24,
                )
            )
        )
        restarted_provider = FakeWeatherProvider(weather_snapshot(now))
        restarted = WeatherAutomation(self.repository, provider=restarted_provider)

        async def start_and_stop():
            await restarted.start()
            status = restarted.status()
            await restarted.close()
            return status

        status = asyncio.run(start_and_stop())

        self.assertTrue(status.settings.enabled)
        self.assertTrue(status.snapshot)
        self.assertEqual(restarted_provider.forecasts, [(37.323, -122.0322)])


if __name__ == "__main__":
    unittest.main()
