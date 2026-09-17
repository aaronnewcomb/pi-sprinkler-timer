"""Command-line entry point for the 3.0 API service."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .api import create_app
from .config import load_settings, read_api_token
from .controller import SprinklerController
from .persistence import SQLiteRepository
from .relay import GPIOZeroRelayBank
from .scheduler import ScheduleRunner
from .weather import WeatherAutomation


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Pi Sprinkler Timer 3.0")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("/etc/open-sprinkler/open-sprinkler.ini"),
    )
    parser.add_argument(
        "--api-token-file",
        type=Path,
        default=Path("/etc/open-sprinkler/api-token"),
    )
    args = parser.parse_args()

    settings = load_settings(args.config)
    api_token = read_api_token(args.api_token_file)
    repository = SQLiteRepository.open(settings.database_path)
    try:
        relays = GPIOZeroRelayBank([station.pin for station in settings.stations])
    except Exception:
        repository.close()
        raise
    controller = SprinklerController(
        settings.stations,
        relays,
        max_duration_seconds=settings.max_duration_seconds,
        run_recorder=repository,
    )
    scheduler = ScheduleRunner(
        repository,
        controller,
        timezone=settings.timezone,
        poll_seconds=settings.scheduler_poll_seconds,
        grace_seconds=settings.scheduler_grace_seconds,
    )
    weather = WeatherAutomation(
        repository,
        poll_seconds=settings.weather_poll_seconds,
    )
    app = create_app(
        controller,
        api_token,
        repository=repository,
        scheduler=scheduler,
        weather=weather,
        secure_cookies=settings.secure_cookies,
    )

    uvicorn.run(
        app,
        host=settings.listen_host,
        port=settings.listen_port,
        workers=1,
        access_log=True,
    )


if __name__ == "__main__":
    main()
