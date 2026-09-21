"""Persisted, live-safe controller configuration overrides."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

from .config import RuntimeSettings
from .controller import SprinklerController, StationDefinition
from .persistence import SQLiteRepository

if TYPE_CHECKING:
    from .scheduler import ScheduleRunner

StopAction = Literal["station", "schedule", "day"]
STATE_KEY = "controller_settings_json"


@dataclass(frozen=True, slots=True)
class EditableControllerSettings:
    stations: tuple[StationDefinition, ...]
    timezone: str
    max_duration_seconds: int
    stop_action: StopAction = "schedule"


class ControllerSettingsManager:
    """Store settings and apply changes that are safe without a relay restart."""

    def __init__(
        self,
        repository: SQLiteRepository,
        defaults: RuntimeSettings,
    ) -> None:
        self._repository = repository
        self._defaults = defaults
        self._settings = self._load()
        self._active_pins = tuple(station.pin for station in self._settings.stations)
        self._controller: SprinklerController | None = None
        self._scheduler: ScheduleRunner | None = None

    @property
    def settings(self) -> EditableControllerSettings:
        return self._settings

    @property
    def restart_required(self) -> bool:
        return (
            tuple(station.pin for station in self._settings.stations)
            != self._active_pins
        )

    def bind(
        self,
        controller: SprinklerController,
        scheduler: ScheduleRunner | None = None,
    ) -> None:
        self._controller = controller
        self._scheduler = scheduler

    async def configure(
        self,
        *,
        station_names: list[str],
        gpio_pins: list[int],
        timezone: str,
        max_duration_seconds: int,
        stop_action: str,
    ) -> EditableControllerSettings:
        updated = _validated_settings(
            station_names=station_names,
            gpio_pins=gpio_pins,
            timezone=timezone,
            max_duration_seconds=max_duration_seconds,
            stop_action=stop_action,
            expected_station_count=len(self._settings.stations),
        )
        self._repository.set_controller_state(STATE_KEY, _serialize(updated))
        self._settings = updated
        if self._controller is not None:
            await self._controller.reconfigure(
                station_names=[station.name for station in updated.stations],
                max_duration_seconds=updated.max_duration_seconds,
            )
        if self._scheduler is not None:
            self._scheduler.update_timezone(updated.timezone)
        return updated

    def _load(self) -> EditableControllerSettings:
        default = EditableControllerSettings(
            stations=tuple(self._defaults.stations),
            timezone=self._defaults.timezone,
            max_duration_seconds=self._defaults.max_duration_seconds,
        )
        stored = self._repository.get_controller_state(STATE_KEY)
        if stored is None:
            return default
        try:
            payload = json.loads(stored)
            return _validated_settings(
                station_names=payload["station_names"],
                gpio_pins=payload["gpio_pins"],
                timezone=payload["timezone"],
                max_duration_seconds=payload["max_duration_seconds"],
                stop_action=payload.get("stop_action", "schedule"),
                expected_station_count=len(default.stations),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("Stored controller settings are invalid") from error


def _validated_settings(
    *,
    station_names: list[str],
    gpio_pins: list[int],
    timezone: str,
    max_duration_seconds: int,
    stop_action: str,
    expected_station_count: int,
) -> EditableControllerSettings:
    names = [str(name).strip() for name in station_names]
    pins = [int(pin) for pin in gpio_pins]
    if len(names) != expected_station_count or len(pins) != expected_station_count:
        raise ValueError(f"Exactly {expected_station_count} stations are required")
    if any(not name for name in names):
        raise ValueError("Station names must not be empty")
    if len(pins) != len(set(pins)):
        raise ValueError("Station GPIO pins must be unique")
    if any(pin < 0 or pin > 27 for pin in pins):
        raise ValueError("Station GPIO pins must be BCM numbers from 0 through 27")
    timezone = timezone.strip()
    ZoneInfo(timezone)
    if max_duration_seconds < 60 or max_duration_seconds > 86_400:
        raise ValueError("Maximum duration must be between 60 and 86400 seconds")
    if stop_action not in {"station", "schedule", "day"}:
        raise ValueError("Stop action must be station, schedule, or day")
    return EditableControllerSettings(
        stations=tuple(
            StationDefinition(index, name, pin)
            for index, (name, pin) in enumerate(zip(names, pins, strict=True), start=1)
        ),
        timezone=timezone,
        max_duration_seconds=max_duration_seconds,
        stop_action=stop_action,  # type: ignore[arg-type]
    )


def _serialize(settings: EditableControllerSettings) -> str:
    return json.dumps(
        {
            "station_names": [station.name for station in settings.stations],
            "gpio_pins": [station.pin for station in settings.stations],
            "timezone": settings.timezone,
            "max_duration_seconds": settings.max_duration_seconds,
            "stop_action": settings.stop_action,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
