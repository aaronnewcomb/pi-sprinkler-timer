"""Serialized, safety-oriented sprinkler relay controller."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from .relay import RelayBackend

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StationDefinition:
    id: int
    name: str
    pin: int


@dataclass(frozen=True, slots=True)
class StationState:
    id: int
    name: str
    active: bool


@dataclass(frozen=True, slots=True)
class ControllerStatus:
    stations: tuple[StationState, ...]
    active_station_id: int | None
    active_run_id: int | None
    active_until: datetime | None
    active_source: str | None
    active_schedule_id: int | None


class UnknownStationError(ValueError):
    """Raised when a command addresses a station that does not exist."""


class RunRecorder(Protocol):
    """Persistence operations used by the controller command worker."""

    def start_run(
        self,
        *,
        source: str,
        schedule_id: int | None,
        station_id: int,
        duration_seconds: int,
        started_at: datetime | None = None,
    ) -> int: ...

    def finish_run(
        self,
        run_id: int,
        *,
        outcome: str,
        ended_at: datetime | None = None,
    ) -> None: ...


@dataclass(slots=True)
class _Command:
    name: str
    result: asyncio.Future[Any]
    station_id: int | None = None
    duration_seconds: int | None = None
    source: str | None = None
    schedule_id: int | None = None
    outcome: str | None = None
    station_names: tuple[str, ...] | None = None
    max_duration_seconds: int | None = None


class SprinklerController:
    """Own relay state and process all hardware commands in order."""

    def __init__(
        self,
        stations: list[StationDefinition],
        relays: RelayBackend,
        *,
        max_duration_seconds: int = 7_200,
        run_recorder: RunRecorder | None = None,
    ) -> None:
        if not stations:
            raise ValueError("At least one station is required")
        station_ids = [station.id for station in stations]
        station_pins = [station.pin for station in stations]
        if len(station_ids) != len(set(station_ids)):
            raise ValueError("Station IDs must be unique")
        if len(station_pins) != len(set(station_pins)):
            raise ValueError("Station GPIO pins must be unique")
        if max_duration_seconds < 1:
            raise ValueError("Maximum duration must be positive")

        self._stations = {station.id: station for station in stations}
        self._relays = relays
        self._max_duration_seconds = max_duration_seconds
        self._run_recorder = run_recorder
        self._commands: asyncio.Queue[_Command | None] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._timer_task: asyncio.Task[None] | None = None
        self._active_station_id: int | None = None
        self._active_run_id: int | None = None
        self._active_until: datetime | None = None
        self._active_source: str | None = None
        self._active_schedule_id: int | None = None
        self._next_transient_run_id = 1
        self._run_outcomes: OrderedDict[int, str] = OrderedDict()
        self._run_waiters: dict[int, asyncio.Future[str]] = {}

    @property
    def max_duration_seconds(self) -> int:
        return self._max_duration_seconds

    @property
    def station_ids(self) -> frozenset[int]:
        return frozenset(self._stations)

    @property
    def station_definitions(self) -> tuple[StationDefinition, ...]:
        return tuple(self._stations.values())

    @property
    def is_running(self) -> bool:
        return self._worker_task is not None and not self._worker_task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        self._relays.all_off()
        self._active_station_id = None
        self._active_run_id = None
        self._active_until = None
        self._active_source = None
        self._active_schedule_id = None
        self._worker_task = asyncio.create_task(
            self._command_worker(), name="pi-sprinkler-controller"
        )

    async def close(self) -> None:
        if self.is_running:
            await self._submit("stop_all", outcome="interrupted")
            await self._commands.put(None)
            assert self._worker_task is not None
            await self._worker_task
        else:
            self._relays.all_off()
        self._cancel_timer()
        self._relays.close()
        self._worker_task = None

    async def start_station(
        self,
        station_id: int,
        duration_seconds: int,
        *,
        source: str = "api",
        schedule_id: int | None = None,
    ) -> ControllerStatus:
        if duration_seconds < 1 or duration_seconds > self._max_duration_seconds:
            raise ValueError(
                f"Duration must be between 1 and {self._max_duration_seconds} seconds"
            )
        if not source.strip():
            raise ValueError("Run source must not be empty")
        return await self._submit(
            "start",
            station_id=station_id,
            duration_seconds=duration_seconds,
            source=source.strip(),
            schedule_id=schedule_id,
        )

    async def stop_station(
        self, station_id: int, *, outcome: str = "stopped"
    ) -> ControllerStatus:
        return await self._submit("stop", station_id=station_id, outcome=outcome)

    async def stop_all(self) -> ControllerStatus:
        return await self._submit("stop_all", outcome="stopped")

    async def status(self) -> ControllerStatus:
        return await self._submit("status")

    async def reconfigure(
        self,
        *,
        station_names: list[str],
        max_duration_seconds: int,
    ) -> ControllerStatus:
        names = tuple(name.strip() for name in station_names)
        if len(names) != len(self._stations) or any(not name for name in names):
            raise ValueError("A non-empty name is required for every station")
        if max_duration_seconds < 60 or max_duration_seconds > 86_400:
            raise ValueError("Maximum duration must be between 60 and 86400 seconds")
        return await self._submit(
            "configure",
            station_names=names,
            max_duration_seconds=max_duration_seconds,
        )

    async def wait_for_run(self, run_id: int) -> str:
        if run_id in self._run_outcomes:
            return self._run_outcomes.pop(run_id)
        if run_id != self._active_run_id:
            raise ValueError(f"Run {run_id} is not active or recently completed")
        loop = asyncio.get_running_loop()
        waiter = loop.create_future()
        self._run_waiters[run_id] = waiter
        try:
            return await waiter
        finally:
            self._run_waiters.pop(run_id, None)

    async def _submit(
        self,
        name: str,
        *,
        station_id: int | None = None,
        duration_seconds: int | None = None,
        source: str | None = None,
        schedule_id: int | None = None,
        outcome: str | None = None,
        station_names: tuple[str, ...] | None = None,
        max_duration_seconds: int | None = None,
    ) -> ControllerStatus:
        if not self.is_running:
            raise RuntimeError("Controller is not running")
        loop = asyncio.get_running_loop()
        result: asyncio.Future[ControllerStatus] = loop.create_future()
        await self._commands.put(
            _Command(
                name=name,
                result=result,
                station_id=station_id,
                duration_seconds=duration_seconds,
                source=source,
                schedule_id=schedule_id,
                outcome=outcome,
                station_names=station_names,
                max_duration_seconds=max_duration_seconds,
            )
        )
        return await result

    async def _command_worker(self) -> None:
        while True:
            command = await self._commands.get()
            try:
                if command is None:
                    return
                response = self._dispatch(command)
                if not command.result.cancelled():
                    command.result.set_result(response)
            except Exception as error:  # noqa: BLE001
                # Each command reports its own failure. The worker must remain
                # available for safety commands such as stop_all.
                if command is not None and not command.result.cancelled():
                    # Do not expose the worker's live coroutine frame through
                    # an exception traceback. Some exception consumers clear
                    # traceback frames after handling, which would corrupt the
                    # still-running command worker.
                    error.__traceback__ = None
                    command.result.set_exception(error)
            finally:
                self._commands.task_done()

    def _dispatch(self, command: _Command) -> ControllerStatus:
        if command.name == "start":
            assert command.station_id is not None
            assert command.duration_seconds is not None
            station = self._station(command.station_id)
            self._cancel_timer()
            self._relays.all_off()
            self._finish_active_run("replaced")
            if self._run_recorder is None:
                run_id = self._next_transient_run_id
                self._next_transient_run_id += 1
            else:
                assert command.source is not None
                run_id = self._run_recorder.start_run(
                    source=command.source,
                    schedule_id=command.schedule_id,
                    station_id=station.id,
                    duration_seconds=command.duration_seconds,
                )
            try:
                self._relays.on(station.pin)
            except Exception:
                self._relays.all_off()
                if self._run_recorder is not None:
                    try:
                        self._run_recorder.finish_run(run_id, outcome="failed")
                    except Exception:
                        LOGGER.exception(
                            "Failed to record relay activation failure for run %s",
                            run_id,
                        )
                raise
            self._active_station_id = station.id
            self._active_run_id = run_id
            self._active_until = datetime.now(UTC) + timedelta(
                seconds=command.duration_seconds
            )
            self._active_source = command.source
            self._active_schedule_id = command.schedule_id
            self._timer_task = asyncio.create_task(
                self._expire_after(station.id, command.duration_seconds),
                name=f"pi-sprinkler-station-{station.id}-timer",
            )
        elif command.name == "stop":
            assert command.station_id is not None
            station = self._station(command.station_id)
            self._relays.off(station.pin)
            if self._active_station_id == station.id:
                self._cancel_timer()
                self._finish_active_run(command.outcome or "stopped")
        elif command.name == "stop_all":
            self._cancel_timer()
            self._relays.all_off()
            self._finish_active_run(command.outcome or "stopped")
        elif command.name == "configure":
            assert command.station_names is not None
            assert command.max_duration_seconds is not None
            self._stations = {
                station.id: StationDefinition(station.id, name, station.pin)
                for station, name in zip(
                    self._stations.values(), command.station_names, strict=True
                )
            }
            self._max_duration_seconds = command.max_duration_seconds
        elif command.name != "status":
            raise ValueError(f"Unsupported controller command: {command.name}")
        return self._snapshot()

    def _station(self, station_id: int) -> StationDefinition:
        try:
            return self._stations[station_id]
        except KeyError as error:
            raise UnknownStationError(f"Station {station_id} does not exist") from error

    def _snapshot(self) -> ControllerStatus:
        return ControllerStatus(
            stations=tuple(
                StationState(
                    id=station.id,
                    name=station.name,
                    active=self._relays.is_on(station.pin),
                )
                for station in self._stations.values()
            ),
            active_station_id=self._active_station_id,
            active_run_id=self._active_run_id,
            active_until=self._active_until,
            active_source=self._active_source,
            active_schedule_id=self._active_schedule_id,
        )

    async def _expire_after(self, station_id: int, duration_seconds: int) -> None:
        try:
            await asyncio.sleep(duration_seconds)
            await self.stop_station(station_id, outcome="completed")
        except asyncio.CancelledError:
            return

    def _cancel_timer(self) -> None:
        if self._timer_task is not None and not self._timer_task.done():
            current_task = asyncio.current_task()
            if self._timer_task is not current_task:
                self._timer_task.cancel()
        self._timer_task = None

    def _finish_active_run(self, outcome: str) -> None:
        run_id = self._active_run_id
        if run_id is None:
            return
        persistence_error: Exception | None = None
        if self._run_recorder is not None:
            try:
                self._run_recorder.finish_run(run_id, outcome=outcome)
            except Exception as error:  # noqa: BLE001
                persistence_error = error
        final_outcome = "failed" if persistence_error is not None else outcome
        self._run_outcomes[run_id] = final_outcome
        while len(self._run_outcomes) > 100:
            self._run_outcomes.popitem(last=False)
        waiter = self._run_waiters.get(run_id)
        if waiter is not None and not waiter.done():
            waiter.set_result(final_outcome)
        self._active_station_id = None
        self._active_run_id = None
        self._active_until = None
        self._active_source = None
        self._active_schedule_id = None
        if persistence_error is not None:
            raise persistence_error
