"""3.0 runtime configuration loading."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from .controller import StationDefinition


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    stations: list[StationDefinition]
    max_duration_seconds: int
    listen_host: str
    listen_port: int
    secure_cookies: bool
    database_path: Path
    timezone: str
    scheduler_poll_seconds: int
    scheduler_grace_seconds: int
    weather_poll_seconds: int


def load_settings(path: Path) -> RuntimeSettings:
    parser = configparser.ConfigParser()
    if not parser.read(path):
        raise ValueError(f"Unable to read configuration file: {path}")

    pins = _csv_ints(parser.get("Station GPIOs", "pins"))
    raw_names = parser.get("Station GPIOs", "names", fallback="")
    names = [name.strip() for name in raw_names.split(",") if name.strip()]
    if names and len(names) != len(pins):
        raise ValueError("Station names must match the number of GPIO pins")
    if not names:
        names = [f"Station {index}" for index in range(1, len(pins) + 1)]

    stations = [
        StationDefinition(id=index, name=name, pin=pin)
        for index, (name, pin) in enumerate(zip(names, pins, strict=True), start=1)
    ]
    timezone = parser.get("Scheduler", "timezone", fallback="UTC")
    ZoneInfo(timezone)
    settings = RuntimeSettings(
        stations=stations,
        max_duration_seconds=parser.getint(
            "Controller", "max_duration_seconds", fallback=7_200
        ),
        listen_host=parser.get("Server", "host", fallback="127.0.0.1"),
        listen_port=parser.getint("Server", "port", fallback=8000),
        secure_cookies=parser.getboolean("Server", "secure_cookies", fallback=True),
        database_path=Path(
            parser.get(
                "Storage",
                "database_path",
                fallback="/var/lib/open-sprinkler/open-sprinkler.db",
            )
        ),
        timezone=timezone,
        scheduler_poll_seconds=parser.getint("Scheduler", "poll_seconds", fallback=15),
        scheduler_grace_seconds=parser.getint(
            "Scheduler", "grace_seconds", fallback=300
        ),
        weather_poll_seconds=parser.getint("Weather", "poll_seconds", fallback=900),
    )
    if settings.scheduler_poll_seconds < 1:
        raise ValueError("Scheduler poll interval must be positive")
    if settings.scheduler_grace_seconds < 0:
        raise ValueError("Scheduler grace period must not be negative")
    if settings.weather_poll_seconds < 60:
        raise ValueError("Weather poll interval must be at least 60 seconds")
    return settings


def read_api_token(path: Path) -> str:
    token = path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise ValueError(f"API token must contain at least 32 characters: {path}")
    return token


def _csv_ints(value: str) -> list[int]:
    pins = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not pins:
        raise ValueError("At least one station GPIO pin is required")
    if len(pins) != len(set(pins)):
        raise ValueError("Station GPIO pins must be unique")
    return pins
