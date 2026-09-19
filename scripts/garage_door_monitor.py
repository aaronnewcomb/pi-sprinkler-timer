#!/usr/bin/env python3
"""Publish a garage-door reed-switch state to MQTT."""

from __future__ import annotations

import argparse
import configparser
import logging
import signal
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

LOGGER = logging.getLogger("garage-door-monitor")
DEFAULT_CONFIG_PATH = Path("/etc/pi-sprinkler-garage-door/garage-door.ini")


class InputDevice(Protocol):
    is_active: bool
    when_activated: object
    when_deactivated: object

    def close(self) -> None: ...


class Publisher(Protocol):
    def publish(self, topic: str, payload: str, *, retain: bool) -> None: ...


@dataclass(frozen=True)
class GarageDoorConfig:
    gpio_pin: int
    bounce_time: float
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    mqtt_topic: str
    open_payload: str
    closed_payload: str
    retain: bool
    retry_seconds: float


def load_config(path: Path) -> GarageDoorConfig:
    parser = configparser.ConfigParser(interpolation=None)
    if not parser.read(path, encoding="utf-8"):
        raise ValueError(f"configuration file not found: {path}")
    if not parser.has_section("garage-door"):
        raise ValueError("configuration requires a [garage-door] section")

    section = parser["garage-door"]
    config = GarageDoorConfig(
        gpio_pin=section.getint("gpio_pin", fallback=4),
        bounce_time=section.getfloat("bounce_time", fallback=0.1),
        mqtt_host=section.get("mqtt_host", fallback="").strip(),
        mqtt_port=section.getint("mqtt_port", fallback=1883),
        mqtt_username=section.get("mqtt_username", fallback=""),
        mqtt_password=section.get("mqtt_password", fallback=""),
        mqtt_topic=section.get("mqtt_topic", fallback="").strip(),
        open_payload=section.get("open_payload", fallback="ON"),
        closed_payload=section.get("closed_payload", fallback="OFF"),
        retain=section.getboolean("retain", fallback=False),
        retry_seconds=section.getfloat("retry_seconds", fallback=5.0),
    )

    if not 0 <= config.gpio_pin <= 27:
        raise ValueError("gpio_pin must be a BCM GPIO number from 0 through 27")
    if config.bounce_time < 0:
        raise ValueError("bounce_time must be zero or greater")
    if not config.mqtt_host:
        raise ValueError("mqtt_host is required")
    if not 1 <= config.mqtt_port <= 65535:
        raise ValueError("mqtt_port must be from 1 through 65535")
    if bool(config.mqtt_username) != bool(config.mqtt_password):
        raise ValueError("mqtt_username and mqtt_password must both be set or both be empty")
    if not config.mqtt_topic:
        raise ValueError("mqtt_topic is required")
    if not config.open_payload or not config.closed_payload:
        raise ValueError("open_payload and closed_payload must not be empty")
    if config.retry_seconds <= 0:
        raise ValueError("retry_seconds must be greater than zero")
    return config


class MqttSinglePublisher:
    def __init__(self, config: GarageDoorConfig):
        from paho.mqtt import publish

        self._publish_single = publish.single
        self._hostname = config.mqtt_host
        self._port = config.mqtt_port
        self._auth = None
        if config.mqtt_username:
            self._auth = {
                "username": config.mqtt_username,
                "password": config.mqtt_password,
            }

    def publish(self, topic: str, payload: str, *, retain: bool) -> None:
        self._publish_single(
            topic,
            payload=payload,
            qos=0,
            retain=retain,
            hostname=self._hostname,
            port=self._port,
            auth=self._auth,
        )


class GarageDoorMonitor:
    """Publish the initial input state and each subsequent state change."""

    def __init__(
        self,
        input_device: InputDevice,
        publisher: Publisher,
        config: GarageDoorConfig,
    ) -> None:
        self._input = input_device
        self._publisher = publisher
        self._config = config
        self._last_payload: str | None = None
        self._changed = threading.Event()
        self._input.when_activated = self.notify_changed
        self._input.when_deactivated = self.notify_changed

    def notify_changed(self) -> None:
        self._changed.set()

    def current_payload(self) -> str:
        # pull_up=True means an active/low input is a closed reed switch.
        return (
            self._config.closed_payload
            if self._input.is_active
            else self._config.open_payload
        )

    def publish_current(self) -> bool:
        payload = self.current_payload()
        if payload == self._last_payload:
            return False
        self._publisher.publish(
            self._config.mqtt_topic,
            payload,
            retain=self._config.retain,
        )
        self._last_payload = payload
        LOGGER.info("Published garage door state: %s", payload)
        return True

    def run(self, stop_event: threading.Event) -> None:
        self.notify_changed()
        while not stop_event.is_set():
            if not self._changed.wait(timeout=1.0):
                continue
            self._changed.clear()
            try:
                self.publish_current()
            except Exception:
                LOGGER.exception(
                    "Could not publish garage door state; retrying in %.1f seconds",
                    self._config.retry_seconds,
                )
                if stop_event.wait(self._config.retry_seconds):
                    break
                self.notify_changed()


def build_input_device(config: GarageDoorConfig):
    from gpiozero import DigitalInputDevice
    from gpiozero.pins.lgpio import LGPIOFactory

    factory = LGPIOFactory()
    device = DigitalInputDevice(
        config.gpio_pin,
        pull_up=True,
        bounce_time=config.bounce_time,
        pin_factory=factory,
    )
    return device, factory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="validate configuration without accessing GPIO or MQTT",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        config = load_config(args.config)
    except (OSError, ValueError, configparser.Error) as error:
        LOGGER.error("Invalid configuration: %s", error)
        return 2
    if args.check_config:
        LOGGER.info("Garage door monitor configuration is valid")
        return 0

    stop_event = threading.Event()

    def request_stop(_signum, _frame) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    device = None
    factory = None
    try:
        device, factory = build_input_device(config)
        monitor = GarageDoorMonitor(device, MqttSinglePublisher(config), config)
        LOGGER.info(
            "Monitoring BCM GPIO %d and publishing to %s",
            config.gpio_pin,
            config.mqtt_topic,
        )
        monitor.run(stop_event)
    except Exception:
        LOGGER.exception("Garage door monitor stopped unexpectedly")
        return 1
    finally:
        if device is not None:
            device.close()
        if factory is not None:
            factory.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
