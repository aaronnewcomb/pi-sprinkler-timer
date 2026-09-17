import asyncio
import sys
import unittest
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from open_sprinkler.persistence import ScheduleStep, SQLiteRepository
from open_sprinkler.scheduler import ScheduleRunner


class FakeController:
    def __init__(self, outcomes=None):
        self.calls = []
        self.outcomes = list(outcomes or ["completed"])
        self.next_run_id = 1

    async def start_station(self, station_id, duration_seconds, *, source, schedule_id):
        run_id = self.next_run_id
        self.next_run_id += 1
        self.calls.append((station_id, duration_seconds, source, schedule_id, run_id))
        return SimpleNamespace(active_run_id=run_id)

    async def wait_for_run(self, _run_id):
        return self.outcomes.pop(0) if self.outcomes else "completed"


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.repository = SQLiteRepository.open(":memory:")
        self.repository.initialize()
        self.local_tuesday_0601 = datetime(2026, 9, 15, 13, 1, tzinfo=UTC)

    def tearDown(self):
        self.repository.close()

    def create_schedule(self):
        return self.repository.create_schedule(
            name="Morning",
            enabled=True,
            start_time=time(6, 0),
            days_of_week=(1,),
            steps=(ScheduleStep(1, 60), ScheduleStep(2, 120)),
        )

    def test_due_schedule_is_claimed_once_and_runs_steps_in_order(self):
        schedule = self.create_schedule()
        controller = FakeController(["completed", "completed"])
        runner = ScheduleRunner(
            self.repository,
            controller,
            timezone="America/Los_Angeles",
            grace_seconds=300,
        )

        first = asyncio.run(runner.run_once(now=self.local_tuesday_0601))
        second = asyncio.run(runner.run_once(now=self.local_tuesday_0601))

        self.assertEqual(first, [schedule.id])
        self.assertEqual(second, [])
        self.assertEqual(
            [(call[0], call[1]) for call in controller.calls],
            [(1, 60), (2, 120)],
        )

    def test_schedule_outside_grace_window_is_not_run(self):
        self.create_schedule()
        controller = FakeController()
        runner = ScheduleRunner(
            self.repository,
            controller,
            timezone="America/Los_Angeles",
            grace_seconds=300,
        )

        triggered = asyncio.run(
            runner.run_once(now=self.local_tuesday_0601 + timedelta(minutes=10))
        )

        self.assertEqual(triggered, [])
        self.assertEqual(controller.calls, [])

    def test_rain_delay_suppresses_new_schedule_runs(self):
        self.create_schedule()
        self.repository.set_rain_delay(self.local_tuesday_0601 + timedelta(hours=2))
        controller = FakeController()
        runner = ScheduleRunner(
            self.repository,
            controller,
            timezone="America/Los_Angeles",
        )

        triggered = asyncio.run(runner.run_once(now=self.local_tuesday_0601))

        self.assertEqual(triggered, [])
        self.assertEqual(controller.calls, [])

    def test_weather_delay_suppresses_new_schedule_runs(self):
        self.create_schedule()
        self.repository.set_weather_rain_delay(
            self.local_tuesday_0601 + timedelta(hours=2)
        )
        controller = FakeController()
        runner = ScheduleRunner(
            self.repository,
            controller,
            timezone="America/Los_Angeles",
        )

        triggered = asyncio.run(runner.run_once(now=self.local_tuesday_0601))

        self.assertEqual(triggered, [])
        self.assertEqual(controller.calls, [])

    def test_interrupted_step_aborts_remaining_schedule(self):
        schedule = self.create_schedule()
        controller = FakeController(["stopped"])
        runner = ScheduleRunner(
            self.repository,
            controller,
            timezone="America/Los_Angeles",
        )

        triggered = asyncio.run(runner.run_once(now=self.local_tuesday_0601))

        self.assertEqual(triggered, [schedule.id])
        self.assertEqual(len(controller.calls), 1)

    def test_skipped_station_continues_current_schedule(self):
        schedule = self.create_schedule()
        controller = FakeController(["skipped", "completed"])
        runner = ScheduleRunner(
            self.repository,
            controller,
            timezone="America/Los_Angeles",
        )

        triggered = asyncio.run(runner.run_once(now=self.local_tuesday_0601))

        self.assertEqual(triggered, [schedule.id])
        self.assertEqual(len(controller.calls), 2)
