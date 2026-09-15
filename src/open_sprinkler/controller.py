"""Serialized, safety-oriented sprinkler relay controller."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .relay import RelayBackend


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
    active_until: datetime | None


class UnknownStationError(ValueError):
    """Raised when a command addresses a station that does not exist."""


@dataclass(slots=True)
class _Command:
    name: str
    station_id: int | None
    duration_seconds: int | None
    result: asyncio.Future[Any]


class SprinklerController:
    """Own relay state and process all hardware commands in order."""

    def __init__(
        self,
        stations: list[StationDefinition],
        relays: RelayBackend,
        *,
        max_duration_seconds: int = 7_200,
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
        self._commands: asyncio.Queue[_Command | None] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._timer_task: asyncio.Task[None] | None = None
        self._active_station_id: int | None = None
        self._active_until: datetime | None = None

    @property
    def max_duration_seconds(self) -> int:
        return self._max_duration_seconds

    @property
    def is_running(self) -> bool:
        return self._worker_task is not None and not self._worker_task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        self._relays.all_off()
        self._active_station_id = None
        self._active_until = None
        self._worker_task = asyncio.create_task(
            self._command_worker(), name="open-sprinkler-controller"
        )

    async def close(self) -> None:
        if self.is_running:
            await self.stop_all()
            await self._commands.put(None)
            assert self._worker_task is not None
            await self._worker_task
        else:
            self._relays.all_off()
        self._cancel_timer()
        self._relays.close()
        self._worker_task = None

    async def start_station(
        self, station_id: int, duration_seconds: int
    ) -> ControllerStatus:
        if duration_seconds < 1 or duration_seconds > self._max_duration_seconds:
            raise ValueError(
                f"Duration must be between 1 and {self._max_duration_seconds} seconds"
            )
        return await self._submit("start", station_id, duration_seconds)

    async def stop_station(self, station_id: int) -> ControllerStatus:
        return await self._submit("stop", station_id, None)

    async def stop_all(self) -> ControllerStatus:
        return await self._submit("stop_all", None, None)

    async def status(self) -> ControllerStatus:
        return await self._submit("status", None, None)

    async def _submit(
        self,
        name: str,
        station_id: int | None,
        duration_seconds: int | None,
    ) -> ControllerStatus:
        if not self.is_running:
            raise RuntimeError("Controller is not running")
        loop = asyncio.get_running_loop()
        result: asyncio.Future[ControllerStatus] = loop.create_future()
        await self._commands.put(_Command(name, station_id, duration_seconds, result))
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
            self._relays.on(station.pin)
            self._active_station_id = station.id
            self._active_until = datetime.now(UTC) + timedelta(
                seconds=command.duration_seconds
            )
            self._timer_task = asyncio.create_task(
                self._expire_after(station.id, command.duration_seconds),
                name=f"open-sprinkler-station-{station.id}-timer",
            )
        elif command.name == "stop":
            assert command.station_id is not None
            station = self._station(command.station_id)
            self._relays.off(station.pin)
            if self._active_station_id == station.id:
                self._cancel_timer()
                self._active_station_id = None
                self._active_until = None
        elif command.name == "stop_all":
            self._cancel_timer()
            self._relays.all_off()
            self._active_station_id = None
            self._active_until = None
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
            active_until=self._active_until,
        )

    async def _expire_after(self, station_id: int, duration_seconds: int) -> None:
        try:
            await asyncio.sleep(duration_seconds)
            await self.stop_station(station_id)
        except asyncio.CancelledError:
            return

    def _cancel_timer(self) -> None:
        if self._timer_task is not None and not self._timer_task.done():
            current_task = asyncio.current_task()
            if self._timer_task is not current_task:
                self._timer_task.cancel()
        self._timer_task = None
