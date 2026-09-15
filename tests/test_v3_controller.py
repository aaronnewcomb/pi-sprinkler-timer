import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from open_sprinkler.controller import SprinklerController, StationDefinition


class FakeRelayBank:
    def __init__(self, pins):
        self.states = {pin: False for pin in pins}
        self.operations = []
        self.closed = False

    def on(self, pin):
        self.operations.append(("on", pin))
        self.states[pin] = True

    def off(self, pin):
        self.operations.append(("off", pin))
        self.states[pin] = False

    def is_on(self, pin):
        return self.states[pin]

    def all_off(self):
        self.operations.append(("all_off", None))
        for pin in self.states:
            self.states[pin] = False

    def close(self):
        self.operations.append(("close", None))
        self.closed = True


def make_controller(max_duration_seconds=60):
    relays = FakeRelayBank([5, 6])
    controller = SprinklerController(
        [
            StationDefinition(id=1, name="Front", pin=5),
            StationDefinition(id=2, name="Back", pin=6),
        ],
        relays,
        max_duration_seconds=max_duration_seconds,
    )
    return controller, relays


class ControllerTests(unittest.TestCase):
    def test_startup_and_shutdown_leave_all_relays_off(self):
        async def scenario():
            controller, relays = make_controller()
            await controller.start()
            self.assertEqual(relays.states, {5: False, 6: False})
            await controller.start_station(1, 30)
            await controller.close()
            self.assertEqual(relays.states, {5: False, 6: False})
            self.assertTrue(relays.closed)

        asyncio.run(scenario())

    def test_switching_stations_is_serialized_and_exclusive(self):
        async def scenario():
            controller, relays = make_controller()
            await controller.start()
            await controller.start_station(1, 30)
            await controller.start_station(2, 30)

            self.assertEqual(relays.states, {5: False, 6: True})
            self.assertEqual(relays.operations[-2:], [("all_off", None), ("on", 6)])
            status = await controller.status()
            self.assertEqual(status.active_station_id, 2)
            self.assertEqual(
                [station.active for station in status.stations], [False, True]
            )
            await controller.close()

        asyncio.run(scenario())

    def test_station_stops_automatically_at_duration_limit(self):
        async def scenario():
            controller, relays = make_controller()
            await controller.start()
            await controller.start_station(1, 1)
            await asyncio.sleep(1.1)
            status = await controller.status()
            self.assertIsNone(status.active_station_id)
            self.assertEqual(relays.states, {5: False, 6: False})
            await controller.close()

        asyncio.run(scenario())

    def test_invalid_station_and_duration_are_rejected(self):
        async def scenario():
            controller, _relays = make_controller(max_duration_seconds=10)
            await controller.start()
            with self.assertRaisesRegex(ValueError, "between 1 and 10"):
                await controller.start_station(1, 11)
            with self.assertRaisesRegex(ValueError, "does not exist"):
                await controller.start_station(99, 5)
            await controller.close()

        asyncio.run(scenario())
