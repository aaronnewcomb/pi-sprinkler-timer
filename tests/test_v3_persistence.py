import sys
import tempfile
import unittest
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from open_sprinkler.persistence import (
    ScheduleNotFoundError,
    ScheduleStep,
    SQLiteRepository,
)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.repository = SQLiteRepository.open(":memory:")
        self.now = datetime(2026, 9, 15, 15, 0, tzinfo=UTC)
        self.repository.initialize(now=self.now)

    def tearDown(self):
        self.repository.close()

    def test_schedule_crud_preserves_order_and_claims_once_per_date(self):
        schedule = self.repository.create_schedule(
            name=" Morning ",
            enabled=True,
            start_time=time(6, 30, 45),
            days_of_week=(4, 0, 2, 2),
            steps=(ScheduleStep(2, 120), ScheduleStep(1, 60)),
            now=self.now,
        )

        self.assertEqual(schedule.name, "Morning")
        self.assertEqual(schedule.start_time, time(6, 30))
        self.assertEqual(schedule.days_of_week, (0, 2, 4))
        self.assertEqual([step.station_id for step in schedule.steps], [2, 1])
        self.assertTrue(self.repository.claim_schedule(schedule.id, date(2026, 9, 15)))
        self.assertFalse(self.repository.claim_schedule(schedule.id, date(2026, 9, 15)))

        updated = self.repository.update_schedule(
            schedule.id,
            name="Evening",
            enabled=False,
            start_time=time(20, 0),
            days_of_week=(1, 3),
            steps=(ScheduleStep(1, 90),),
            now=self.now + timedelta(minutes=1),
        )
        self.assertEqual(updated.name, "Evening")
        self.assertFalse(updated.enabled)
        self.assertEqual(len(self.repository.list_schedules()), 1)

        self.repository.delete_schedule(schedule.id)
        with self.assertRaises(ScheduleNotFoundError):
            self.repository.get_schedule(schedule.id)

    def test_rain_delay_round_trips_in_utc(self):
        until = self.now + timedelta(hours=12)
        self.repository.set_rain_delay(until)
        self.assertEqual(self.repository.get_rain_delay(), until)
        self.repository.set_rain_delay(None)
        self.assertIsNone(self.repository.get_rain_delay())

    def test_expired_manual_hold_does_not_clear_weather_hold(self):
        self.repository.set_manual_rain_delay(self.now - timedelta(hours=1))
        weather_until = self.now + timedelta(hours=8)
        self.repository.set_weather_rain_delay(weather_until)

        self.repository.clear_expired_rain_delays(self.now)

        self.assertIsNone(self.repository.get_manual_rain_delay())
        self.assertEqual(self.repository.get_weather_rain_delay(), weather_until)

    def test_open_runs_are_marked_interrupted_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "controller.db"
            first = SQLiteRepository.open(path)
            first.initialize(now=self.now)
            run_id = first.start_run(
                source="api",
                schedule_id=None,
                station_id=1,
                duration_seconds=60,
                started_at=self.now,
            )
            first.close()

            restarted = SQLiteRepository.open(path)
            restarted.initialize(now=self.now + timedelta(minutes=2))
            run = restarted.list_runs()[0]
            restarted.close()

        self.assertEqual(run.id, run_id)
        self.assertEqual(run.outcome, "interrupted")
        self.assertEqual(run.ended_at, self.now + timedelta(minutes=2))

    def test_run_history_records_completion(self):
        run_id = self.repository.start_run(
            source="schedule",
            schedule_id=None,
            station_id=3,
            duration_seconds=180,
            started_at=self.now,
        )
        self.repository.finish_run(
            run_id,
            outcome="completed",
            ended_at=self.now + timedelta(minutes=3),
        )

        run = self.repository.list_runs(limit=1)[0]
        self.assertEqual(run.station_id, 3)
        self.assertEqual(run.outcome, "completed")
        self.assertEqual(run.ended_at, self.now + timedelta(minutes=3))
