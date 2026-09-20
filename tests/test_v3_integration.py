import asyncio
import sys
import unittest
from datetime import UTC, datetime, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pi_sprinkler.controller import SprinklerController, StationDefinition
from pi_sprinkler.persistence import ScheduleStep, SQLiteRepository
from pi_sprinkler.scheduler import ScheduleRunner


class FakeRelayBank:
    def __init__(self):
        self.states = {5: False}

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


class IntegrationTests(unittest.TestCase):
    def test_due_schedule_runs_through_controller_and_records_history(self):
        async def scenario():
            repository = SQLiteRepository.open(":memory:")
            repository.initialize()
            relays = FakeRelayBank()
            controller = SprinklerController(
                [StationDefinition(id=1, name="Front", pin=5)],
                relays,
                run_recorder=repository,
            )
            schedule = repository.create_schedule(
                name="Morning",
                enabled=True,
                start_time=time(6, 0),
                days_of_week=(1,),
                steps=(ScheduleStep(1, 1),),
            )
            runner = ScheduleRunner(
                repository,
                controller,
                timezone="America/Los_Angeles",
                grace_seconds=300,
            )
            await controller.start()

            triggered = await runner.run_once(
                now=datetime(2026, 9, 15, 13, 1, tzinfo=UTC)
            )

            self.assertEqual(triggered, [schedule.id])
            self.assertEqual(relays.states, {5: False})
            history = repository.list_runs()
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0].outcome, "completed")
            self.assertEqual(history[0].source, "schedule")
            self.assertEqual(history[0].schedule_id, schedule.id)

            await controller.close()
            repository.close()

        asyncio.run(scenario())
