#!/usr/bin/env python3
"""Watch the physical shutdown button and request an orderly poweroff."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
from collections.abc import Callable, Sequence
from threading import Event

LOGGER = logging.getLogger("pi-sprinkler-shutdown-button")
DEFAULT_BCM_PIN = 3
DEFAULT_BOUNCE_TIME = 0.2
POWER_OFF_COMMAND = ("/usr/bin/systemctl", "poweroff")


class ShutdownListener:
    """Connect a GPIO Zero button to an idempotent poweroff request."""

    def __init__(
        self,
        button,
        shutdown_runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        command: Sequence[str] = POWER_OFF_COMMAND,
    ) -> None:
        self.button = button
        self.shutdown_runner = shutdown_runner
        self.command = tuple(command)
        self.shutdown_requested = False
        self.button.when_pressed = self.request_shutdown

    def request_shutdown(self) -> None:
        """Request poweroff once for each button press sequence."""
        if self.shutdown_requested:
            return

        self.shutdown_requested = True
        LOGGER.warning("Shutdown button pressed; requesting orderly poweroff")
        result = self.shutdown_runner(self.command, check=False)
        if result.returncode != 0:
            self.shutdown_requested = False
            LOGGER.error("Poweroff request failed with exit status %s", result.returncode)


def build_button(pin: int, bounce_time: float):
    """Build a GPIO Zero button using the modern lgpio pin factory."""
    try:
        from gpiozero import Button
        from gpiozero.pins.lgpio import LGPIOFactory
    except ImportError as exc:  # pragma: no cover - exercised on an unprovisioned host
        raise RuntimeError(
            "GPIO Zero and lgpio are required; install python3-gpiozero and python3-lgpio"
        ) from exc

    return Button(
        pin,
        pull_up=True,
        bounce_time=bounce_time,
        pin_factory=LGPIOFactory(),
    )


def _positive_float(value: str) -> float:
    result = float(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pin",
        type=int,
        default=int(os.environ.get("BUTTON_BCM_PIN", DEFAULT_BCM_PIN)),
        help="BCM GPIO number (default: %(default)s)",
    )
    parser.add_argument(
        "--bounce-time",
        type=_positive_float,
        default=float(os.environ.get("BUTTON_BOUNCE_TIME", DEFAULT_BOUNCE_TIME)),
        help="GPIO Zero debounce interval in seconds (default: %(default)s)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not 0 <= args.pin <= 27:
        raise SystemExit("--pin must be a BCM GPIO number from 0 through 27")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    stopped = Event()

    def stop(_signum, _frame) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    button = build_button(args.pin, args.bounce_time)
    ShutdownListener(button)
    LOGGER.info("Listening for a low button press on BCM GPIO %s", args.pin)
    try:
        while not stopped.wait(60):
            pass
    finally:
        button.close()
        LOGGER.info("Shutdown button listener stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
