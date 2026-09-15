"""Command-line entry point for the 3.0 API service."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .api import create_app
from .config import load_settings, read_api_token
from .controller import SprinklerController
from .relay import GPIOZeroRelayBank


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Open Sprinkler 3.0")
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
    relays = GPIOZeroRelayBank([station.pin for station in settings.stations])
    controller = SprinklerController(
        settings.stations,
        relays,
        max_duration_seconds=settings.max_duration_seconds,
    )
    app = create_app(controller, read_api_token(args.api_token_file))

    uvicorn.run(
        app,
        host=settings.listen_host,
        port=settings.listen_port,
        workers=1,
        access_log=True,
    )


if __name__ == "__main__":
    main()
