"""Relay abstractions and the Raspberry Pi GPIO Zero implementation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class RelayBackend(Protocol):
    """Synchronous relay operations owned by the controller process."""

    def on(self, pin: int) -> None: ...

    def off(self, pin: int) -> None: ...

    def is_on(self, pin: int) -> bool: ...

    def all_off(self) -> None: ...

    def close(self) -> None: ...


class GPIOZeroRelayBank:
    """Control active-low relays with GPIO Zero and the lgpio backend."""

    def __init__(self, pins: Sequence[int]) -> None:
        from gpiozero import OutputDevice
        from gpiozero.pins.lgpio import LGPIOFactory

        self._factory = LGPIOFactory()
        self._devices: dict[int, OutputDevice] = {}
        try:
            for pin in pins:
                self._devices[pin] = OutputDevice(
                    pin,
                    active_high=False,
                    initial_value=False,
                    pin_factory=self._factory,
                )
        except Exception:
            self.close()
            raise

    def on(self, pin: int) -> None:
        self._devices[pin].on()

    def off(self, pin: int) -> None:
        self._devices[pin].off()

    def is_on(self, pin: int) -> bool:
        return self._devices[pin].is_active

    def all_off(self) -> None:
        for device in self._devices.values():
            device.off()

    def close(self) -> None:
        for device in self._devices.values():
            device.close()
        self._devices.clear()
        if getattr(self, "_factory", None) is not None:
            self._factory.close()
            self._factory = None
