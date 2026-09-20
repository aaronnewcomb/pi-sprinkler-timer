import asyncio
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    import httpx

    from open_sprinkler.api import create_app
    from open_sprinkler.config import RuntimeSettings
    from open_sprinkler.controller import SprinklerController, StationDefinition
    from open_sprinkler.controller_settings import ControllerSettingsManager
    from open_sprinkler.persistence import SQLiteRepository
    from open_sprinkler.weather import (
        DailyForecast,
        HourlyPrecipitation,
        ResolvedLocation,
        WeatherAutomation,
        WeatherSnapshot,
    )
except ModuleNotFoundError:
    V3_API_DEPENDENCIES_AVAILABLE = False
else:
    V3_API_DEPENDENCIES_AVAILABLE = True


class FakeRelayBank:
    def __init__(self):
        self.states = {5: False, 6: False}

    def on(self, pin):
        self.states[pin] = True

    def off(self, pin):
        self.states[pin] = False

    def is_on(self, pin):
        return self.states[pin]

    def all_off(self):
        for pin in self.states:
            self.states[pin] = False

    def close(self):
        pass


class FakeWeatherProvider:
    async def resolve_location(self, _postal_code):
        return ResolvedLocation(37.323, -122.0322, "Cupertino, California, US")

    async def forecast(self, _latitude, _longitude):
        now = datetime.now(UTC)
        return WeatherSnapshot(
            observed_at=now,
            temperature_f=68,
            weather_code=61,
            precipitation_inches=0.05,
            hourly_precipitation=(
                HourlyPrecipitation(now, 0.15),
                HourlyPrecipitation(now + timedelta(hours=1), 0.15),
            ),
            daily=(
                DailyForecast(now.date(), 61, 71, 54, 0.3, 80),
                DailyForecast((now + timedelta(days=1)).date(), 2, 74, 52, 0, 10),
            ),
        )


def make_app():
    controller = SprinklerController(
        [
            StationDefinition(id=1, name="Front", pin=5),
            StationDefinition(id=2, name="Back", pin=6),
        ],
        FakeRelayBank(),
        max_duration_seconds=60,
    )
    return create_app(controller, "test-token")


def make_persistent_app():
    repository = SQLiteRepository.open(":memory:")
    controller = SprinklerController(
        [
            StationDefinition(id=1, name="Front", pin=5),
            StationDefinition(id=2, name="Back", pin=6),
        ],
        FakeRelayBank(),
        max_duration_seconds=60,
        run_recorder=repository,
    )
    return create_app(controller, "test-token", repository=repository)


def make_browser_app():
    repository = SQLiteRepository.open(":memory:")
    repository.initialize()
    stations = [
        StationDefinition(id=1, name="Front", pin=5),
        StationDefinition(id=2, name="Back", pin=6),
    ]
    controller = SprinklerController(
        stations,
        FakeRelayBank(),
        max_duration_seconds=7_200,
        run_recorder=repository,
    )
    weather = WeatherAutomation(repository, provider=FakeWeatherProvider())
    runtime = RuntimeSettings(
        stations=stations,
        max_duration_seconds=7_200,
        listen_host="127.0.0.1",
        listen_port=8000,
        secure_cookies=False,
        database_path=Path(":memory:"),
        timezone="America/Los_Angeles",
        scheduler_poll_seconds=15,
        scheduler_grace_seconds=300,
        weather_poll_seconds=900,
    )
    manager = ControllerSettingsManager(repository, runtime)
    manager.bind(controller)
    return create_app(
        controller,
        "test-token",
        repository=repository,
        weather=weather,
        settings_manager=manager,
        secure_cookies=False,
    )


async def request_scenario(callback, app_factory=make_app):
    app = app_factory()
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        await callback(client)


@unittest.skipUnless(
    V3_API_DEPENDENCIES_AVAILABLE,
    "Install the v3 development dependencies to run API tests",
)
class ApiTests(unittest.TestCase):
    def test_health_does_not_require_authentication(self):
        async def scenario(client):
            response = await client.get("/api/v1/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "ok")

        asyncio.run(request_scenario(scenario))

    def test_status_and_control_require_bearer_token(self):
        async def scenario(client):
            response = await client.get("/api/v1/status")
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers["www-authenticate"], "Bearer")

            response = await client.get(
                "/api/v1/status", headers={"Authorization": "Bearer wrong-token"}
            )
            self.assertEqual(response.status_code, 401)

        asyncio.run(request_scenario(scenario))

    def test_start_status_stop_flow(self):
        async def scenario(client):
            headers = {"Authorization": "Bearer test-token"}
            response = await client.post(
                "/api/v1/stations/1/start",
                headers=headers,
                json={"duration_seconds": 30},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["active_station_id"], 1)
            self.assertTrue(response.json()["stations"][0]["active"])

            response = await client.get("/api/v1/status", headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["active_station_id"], 1)

            response = await client.post("/api/v1/actions/stop-all", headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.json()["active_station_id"])
            self.assertTrue(
                all(not station["active"] for station in response.json()["stations"])
            )

        asyncio.run(request_scenario(scenario))

    def test_unknown_station_and_unsafe_duration_are_rejected(self):
        async def scenario(client):
            headers = {"Authorization": "Bearer test-token"}
            response = await client.post(
                "/api/v1/stations/99/start",
                headers=headers,
                json={"duration_seconds": 30},
            )
            self.assertEqual(response.status_code, 404)

            response = await client.post(
                "/api/v1/stations/1/start",
                headers=headers,
                json={"duration_seconds": 61},
            )
            self.assertEqual(response.status_code, 422)

        asyncio.run(request_scenario(scenario))

    def test_schedule_crud_validates_stations(self):
        async def scenario(client):
            headers = {"Authorization": "Bearer test-token"}
            schedule = {
                "name": "Morning",
                "enabled": True,
                "start_time": "06:30",
                "days_of_week": [0, 2, 4],
                "steps": [
                    {"station_id": 1, "duration_seconds": 30},
                    {"station_id": 2, "duration_seconds": 45},
                ],
            }
            response = await client.post(
                "/api/v1/schedules", headers=headers, json=schedule
            )
            self.assertEqual(response.status_code, 201)
            schedule_id = response.json()["id"]

            response = await client.get("/api/v1/schedules", headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()), 1)

            schedule["name"] = "Updated"
            response = await client.put(
                f"/api/v1/schedules/{schedule_id}",
                headers=headers,
                json=schedule,
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["name"], "Updated")

            invalid = dict(schedule)
            invalid["steps"] = [{"station_id": 99, "duration_seconds": 30}]
            response = await client.post(
                "/api/v1/schedules", headers=headers, json=invalid
            )
            self.assertEqual(response.status_code, 422)

            response = await client.delete(
                f"/api/v1/schedules/{schedule_id}", headers=headers
            )
            self.assertEqual(response.status_code, 204)

        asyncio.run(request_scenario(scenario, make_persistent_app))

    def test_rain_delay_and_run_history_endpoints(self):
        async def scenario(client):
            headers = {"Authorization": "Bearer test-token"}
            until = datetime.now(UTC) + timedelta(hours=12)
            response = await client.put(
                "/api/v1/rain-delay",
                headers=headers,
                json={"until": until.isoformat()},
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["active"])

            response = await client.post(
                "/api/v1/stations/1/start",
                headers=headers,
                json={"duration_seconds": 30},
            )
            self.assertEqual(response.status_code, 200)
            response = await client.post("/api/v1/stations/1/stop", headers=headers)
            self.assertEqual(response.status_code, 200)

            response = await client.get("/api/v1/history", headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()), 1)
            self.assertEqual(response.json()[0]["outcome"], "stopped")

            response = await client.delete("/api/v1/rain-delay", headers=headers)
            self.assertEqual(response.status_code, 204)

        asyncio.run(request_scenario(scenario, make_persistent_app))

    def test_weather_settings_create_independent_automatic_hold(self):
        async def scenario(client):
            headers = {"Authorization": "Bearer test-token"}
            response = await client.put(
                "/api/v1/weather/settings",
                headers=headers,
                json={
                    "enabled": True,
                    "postal_code": "95014",
                    "precipitation_threshold_inches": 0.25,
                    "delay_hours_after_precipitation": 24,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["available"])
            self.assertEqual(
                response.json()["settings"]["location_name"],
                "Cupertino, California, US",
            )

            response = await client.get("/api/v1/rain-delay", headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["sources"], ["weather"])

            manual_until = datetime.now(UTC) + timedelta(hours=48)
            response = await client.put(
                "/api/v1/rain-delay",
                headers=headers,
                json={"until": manual_until.isoformat()},
            )
            self.assertEqual(response.json()["sources"], ["manual", "weather"])

            response = await client.delete("/api/v1/rain-delay", headers=headers)
            self.assertEqual(response.status_code, 204)
            response = await client.get("/api/v1/rain-delay", headers=headers)
            self.assertEqual(response.json()["sources"], ["weather"])

        asyncio.run(request_scenario(scenario, make_browser_app))

    def test_browser_session_requires_csrf_for_control(self):
        async def scenario(client):
            response = await client.post(
                "/api/v1/auth/login", json={"token": "test-token"}
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("open_sprinkler_session", client.cookies)

            response = await client.get("/api/v1/status")
            self.assertEqual(response.status_code, 200)

            response = await client.post("/api/v1/actions/stop-all")
            self.assertEqual(response.status_code, 403)

            response = await client.post(
                "/api/v1/actions/stop-all",
                headers={
                    "X-Open-Sprinkler-CSRF": client.cookies.get("open_sprinkler_csrf")
                },
            )
            self.assertEqual(response.status_code, 200)

        asyncio.run(request_scenario(scenario, make_browser_app))

    def test_controller_settings_persist_and_stage_gpio_restart(self):
        async def scenario(client):
            headers = {"Authorization": "Bearer test-token"}
            response = await client.get("/api/v1/controller-settings", headers=headers)
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            payload.update(
                timezone="UTC",
                max_duration_minutes=30,
                stop_action="day",
            )
            payload["stations"][0]["name"] = "Front Lawn"
            payload["stations"][0]["gpio_pin"] = 12
            payload.pop("restart_required")
            response = await client.put(
                "/api/v1/controller-settings", headers=headers, json=payload
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["restart_required"])
            self.assertEqual(response.json()["stations"][0]["name"], "Front Lawn")

            response = await client.post(
                "/api/v1/stations/1/start",
                headers=headers,
                json={"duration_seconds": 30},
            )
            self.assertEqual(response.json()["stations"][0]["name"], "Front Lawn")
            response = await client.post(
                "/api/v1/actions/configured-stop", headers=headers
            )
            self.assertEqual(response.json()["action"], "day")
            self.assertIsNotNone(response.json()["hold_until"])

        asyncio.run(request_scenario(scenario, make_browser_app))

    def test_web_interface_and_security_headers_are_served(self):
        async def scenario(client):
            response = await client.get("/")
            self.assertEqual(response.status_code, 200)
            self.assertIn("Pi Sprinkler Timer", response.text)
            self.assertIn(
                "default-src 'self'", response.headers["content-security-policy"]
            )
            self.assertEqual(response.headers["x-frame-options"], "DENY")

            response = await client.get("/assets/styles.css")
            self.assertEqual(response.status_code, 200)
            self.assertIn("station-grid", response.text)

        asyncio.run(request_scenario(scenario, make_browser_app))
