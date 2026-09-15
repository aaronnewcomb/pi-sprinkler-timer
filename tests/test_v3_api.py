import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    import httpx

    from open_sprinkler.api import create_app
    from open_sprinkler.controller import SprinklerController, StationDefinition
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


async def request_scenario(callback):
    app = make_app()
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
