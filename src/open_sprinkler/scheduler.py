"""Restart-safe schedule evaluation and sequential station execution."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .controller import SprinklerController
from .persistence import Schedule, SQLiteRepository

LOGGER = logging.getLogger(__name__)


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

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        self._task = asyncio.create_task(
            self._run_loop(), name="open-sprinkler-scheduler"
        )

    async def close(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def run_once(self, *, now: datetime | None = None) -> list[int]:
        now_utc = _as_utc(now or datetime.now(UTC))
        delay_until = self._repository.get_rain_delay()
        if delay_until is not None:
            if now_utc < delay_until:
                return []
            self._repository.set_rain_delay(None)

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
            if outcome != "completed":
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
