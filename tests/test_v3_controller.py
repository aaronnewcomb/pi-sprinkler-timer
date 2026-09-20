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


class FakeRunRecorder:
    def __init__(self):
        self.starts = []
        self.finishes = []

    def start_run(
        self,
        *,
        source,
        schedule_id,
        station_id,
        duration_seconds,
        started_at=None,
    ):
        run_id = len(self.starts) + 1
        self.starts.append((run_id, source, schedule_id, station_id, duration_seconds))
        return run_id

    def finish_run(self, run_id, *, outcome, ended_at=None):
        self.finishes.append((run_id, outcome))


class FailingFinishRecorder(FakeRunRecorder):
    def finish_run(self, run_id, *, outcome, ended_at=None):
        raise OSError("database unavailable")


def make_controller(max_duration_seconds=60, run_recorder=None):
    relays = FakeRelayBank([5, 6])
    controller = SprinklerController(
        [
            StationDefinition(id=1, name="Front", pin=5),
            StationDefinition(id=2, name="Back", pin=6),
        ],
        relays,
        max_duration_seconds=max_duration_seconds,
        run_recorder=run_recorder,
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
            recorder = FakeRunRecorder()
            controller, relays = make_controller(run_recorder=recorder)
            await controller.start()
            started = await controller.start_station(1, 1)
            outcome = await controller.wait_for_run(started.active_run_id)
            status = await controller.status()
            self.assertEqual(outcome, "completed")
            self.assertIsNone(status.active_station_id)
            self.assertEqual(relays.states, {5: False, 6: False})
            self.assertEqual(recorder.finishes, [(1, "completed")])
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

    def test_live_configuration_updates_names_and_future_duration_limit(self):
        async def scenario():
            controller, _relays = make_controller(max_duration_seconds=120)
            await controller.start()
            await controller.reconfigure(
                station_names=["Front Lawn", "Back Lawn"],
                max_duration_seconds=60,
            )
            status = await controller.status()
            self.assertEqual(
                [station.name for station in status.stations],
                ["Front Lawn", "Back Lawn"],
            )
            with self.assertRaisesRegex(ValueError, "between 1 and 60"):
                await controller.start_station(1, 61)
            started = await controller.start_station(
                1, 30, source="schedule", schedule_id=9
            )
            self.assertEqual(started.active_source, "schedule")
            self.assertEqual(started.active_schedule_id, 9)
            await controller.close()

        asyncio.run(scenario())

    def test_persistence_failure_does_not_leave_controller_state_active(self):
        async def scenario():
            controller, relays = make_controller(run_recorder=FailingFinishRecorder())
            await controller.start()
            started = await controller.start_station(1, 30)
            waiter = asyncio.create_task(controller.wait_for_run(started.active_run_id))
            await asyncio.sleep(0)
            with self.assertRaisesRegex(OSError, "database unavailable"):
                await controller.stop_station(1)

            self.assertEqual(await waiter, "failed")
            status = await controller.status()
            self.assertIsNone(status.active_station_id)
            self.assertIsNone(status.active_run_id)
            self.assertEqual(relays.states, {5: False, 6: False})
            await controller.close()

        asyncio.run(scenario())
