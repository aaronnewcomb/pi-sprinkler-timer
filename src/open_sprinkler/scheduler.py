"""Restart-safe schedule evaluation and sequential station execution."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .controller import SprinklerController
from .persistence import Schedule, SQLiteRepository

LOGGER = logging.getLogger(__name__)
TEST_STEP_SECONDS = 30


class ScheduleTestBusyError(RuntimeError):
    """Raised when a schedule test cannot safely start."""


@dataclass(frozen=True, slots=True)
class ScheduleTestStatus:
    running: bool
    schedule_ids: tuple[int, ...]
    current_schedule_id: int | None
    current_station_id: int | None
    completed_steps: int
    total_steps: int
    outcome: str | None
    error: str | None


class ScheduleRunner:
    """Claim due schedules and run their station steps in order."""

    def __init__(
        self,
        repository: SQLiteRepository,
        controller: SprinklerController,
        *,
        timezone: str,
        poll_seconds: int = 15,
        grace_seconds: int = 300,
    ) -> None:
        if poll_seconds < 1:
            raise ValueError("Scheduler poll interval must be positive")
        if grace_seconds < 0:
            raise ValueError("Scheduler grace period must not be negative")
        self._repository = repository
        self._controller = controller
        self._timezone = ZoneInfo(timezone)
        self._poll_seconds = poll_seconds
        self._grace_seconds = grace_seconds
        self._task: asyncio.Task[None] | None = None
        self._execution_lock = asyncio.Lock()
        self._test_task: asyncio.Task[None] | None = None
        self._test_stop_requested = False
        self._test_status = ScheduleTestStatus(
            running=False,
            schedule_ids=(),
            current_schedule_id=None,
            current_station_id=None,
            completed_steps=0,
            total_steps=0,
            outcome=None,
            error=None,
        )

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def timezone(self) -> ZoneInfo:
        return self._timezone

    @property
    def test_status(self) -> ScheduleTestStatus:
        return self._test_status

    def update_timezone(self, timezone: str) -> None:
        self._timezone = ZoneInfo(timezone)

    async def start(self) -> None:
        if self.is_running:
            return
        self._task = asyncio.create_task(
            self._run_loop(), name="open-sprinkler-scheduler"
        )

    async def close(self) -> None:
        if self._test_task is not None and not self._test_task.done():
            await self.stop_test()
        self._test_task = None
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def run_once(self, *, now: datetime | None = None) -> list[int]:
        if self._test_status.running:
            return []
        async with self._execution_lock:
            return await self._run_once_locked(now=now)

    async def _run_once_locked(self, *, now: datetime | None = None) -> list[int]:
        now_utc = _as_utc(now or datetime.now(UTC))
        self._repository.clear_expired_rain_delays(now_utc)
        delay_until = self._repository.get_rain_delay()
        if delay_until is not None and now_utc < delay_until:
            return []

        local_now = now_utc.astimezone(self._timezone)
        triggered: list[int] = []
        for schedule in self._repository.list_schedules():
            if not self._is_due(schedule, local_now):
                continue
            if not self._repository.claim_schedule(schedule.id, local_now.date()):
                continue
            triggered.append(schedule.id)
            await self._execute_schedule(schedule)
        return triggered

    async def start_test(self, schedule_ids: list[int]) -> ScheduleTestStatus:
        if not schedule_ids:
            raise ValueError("Select at least one schedule to test")
        if len(schedule_ids) != len(set(schedule_ids)):
            raise ValueError("Schedule test selections must be unique")
        if self._test_status.running or self._execution_lock.locked():
            raise ScheduleTestBusyError(
                "A schedule or schedule test is already running"
            )
        controller_status = await self._controller.status()
        if controller_status.active_station_id is not None:
            raise ScheduleTestBusyError(
                "Stop active watering before starting a schedule test"
            )
        schedules = [self._repository.get_schedule(item) for item in schedule_ids]
        self._test_status = ScheduleTestStatus(
            running=True,
            schedule_ids=tuple(schedule_ids),
            current_schedule_id=None,
            current_station_id=None,
            completed_steps=0,
            total_steps=sum(len(schedule.steps) for schedule in schedules),
            outcome=None,
            error=None,
        )
        self._test_stop_requested = False
        self._test_task = asyncio.create_task(
            self._run_test(schedules), name="open-sprinkler-schedule-test"
        )
        return self._test_status

    async def stop_test(self) -> ScheduleTestStatus:
        task = self._test_task
        if task is None or task.done() or not self._test_status.running:
            return self._test_status
        self._test_stop_requested = True
        controller_status = await self._controller.status()
        if controller_status.active_source == "schedule-test":
            await self._controller.stop_all()
        await task
        return self._test_status

    async def _run_test(self, schedules: list[Schedule]) -> None:
        outcome = "completed"
        error_message = None
        try:
            async with self._execution_lock:
                for schedule in schedules:
                    for step in schedule.steps:
                        if self._test_stop_requested:
                            outcome = "stopped"
                            return
                        self._update_test_status(
                            current_schedule_id=schedule.id,
                            current_station_id=step.station_id,
                        )
                        status = await self._controller.start_station(
                            step.station_id,
                            TEST_STEP_SECONDS,
                            source="schedule-test",
                            schedule_id=schedule.id,
                        )
                        if status.active_run_id is None:
                            raise RuntimeError("Controller did not create a run ID")
                        run_outcome = await self._controller.wait_for_run(
                            status.active_run_id
                        )
                        if run_outcome != "completed":
                            outcome = "stopped"
                            return
                        self._update_test_status(
                            completed_steps=self._test_status.completed_steps + 1
                        )
        except asyncio.CancelledError:
            outcome = "interrupted"
            raise
        except Exception as error:
            LOGGER.exception("Schedule test failed")
            outcome = "failed"
            error_message = str(error)
            try:
                controller_status = await self._controller.status()
                if controller_status.active_source == "schedule-test":
                    await self._controller.stop_all()
            except Exception:
                LOGGER.exception("Failed to stop relays after schedule test failure")
        finally:
            self._test_stop_requested = False
            self._test_status = ScheduleTestStatus(
                running=False,
                schedule_ids=self._test_status.schedule_ids,
                current_schedule_id=None,
                current_station_id=None,
                completed_steps=self._test_status.completed_steps,
                total_steps=self._test_status.total_steps,
                outcome=outcome,
                error=error_message,
            )

    def _update_test_status(
        self,
        *,
        current_schedule_id: int | None = None,
        current_station_id: int | None = None,
        completed_steps: int | None = None,
    ) -> None:
        self._test_status = ScheduleTestStatus(
            running=True,
            schedule_ids=self._test_status.schedule_ids,
            current_schedule_id=(
                current_schedule_id
                if current_schedule_id is not None
                else self._test_status.current_schedule_id
            ),
            current_station_id=(
                current_station_id
                if current_station_id is not None
                else self._test_status.current_station_id
            ),
            completed_steps=(
                completed_steps
                if completed_steps is not None
                else self._test_status.completed_steps
            ),
            total_steps=self._test_status.total_steps,
            outcome=None,
            error=None,
        )

    def _is_due(self, schedule: Schedule, local_now: datetime) -> bool:
        if not schedule.enabled or local_now.weekday() not in schedule.days_of_week:
            return False
        if schedule.last_started_local_date == local_now.date():
            return False
        scheduled = datetime.combine(
            local_now.date(), schedule.start_time, tzinfo=self._timezone
        )
        elapsed = (local_now - scheduled).total_seconds()
        return 0 <= elapsed <= self._grace_seconds

    async def _execute_schedule(self, schedule: Schedule) -> None:
        for step in schedule.steps:
            status = await self._controller.start_station(
                step.station_id,
                step.duration_seconds,
                source="schedule",
                schedule_id=schedule.id,
            )
            if status.active_run_id is None:
                raise RuntimeError("Controller did not create a run ID")
            outcome = await self._controller.wait_for_run(status.active_run_id)
            if outcome not in {"completed", "skipped"}:
                LOGGER.info(
                    "Schedule %s stopped after run %s ended as %s",
                    schedule.id,
                    status.active_run_id,
                    outcome,
                )
                return

    async def _run_loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Scheduled evaluation failed")
            await asyncio.sleep(self._poll_seconds)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Scheduler datetimes must include a timezone")
    return value.astimezone(UTC)
