#!/usr/bin/python3

"""GPIO Zero relay access for the sprinkler scheduler.

Relay boards supported by this project are active-low: driving a GPIO low
energizes a relay. GPIO Zero exposes logical on/off operations, so callers do
not need to work with electrical levels directly.
"""


class RelayBank:
    """Own and control the configured active-low relay GPIO lines."""

    def __init__(self, pins, device_factory=None, pin_factory=None):
        if device_factory is None:
            from gpiozero import OutputDevice

            device_factory = OutputDevice

        self._owns_pin_factory = pin_factory is None
        if pin_factory is None:
            from gpiozero.pins.lgpio import LGPIOFactory

            pin_factory = LGPIOFactory()

        self._pin_factory = pin_factory
        self._devices = {}
        try:
            for pin in pins:
                self._devices[pin] = device_factory(
                    pin,
                    active_high=False,
                    initial_value=False,
                    pin_factory=pin_factory,
                )
        except Exception:
            self.close()
            raise

    @property
    def pins(self):
        return list(self._devices)

    def on(self, pin):
        self._devices[pin].on()

    def off(self, pin):
        self._devices[pin].off()

    def is_on(self, pin):
        return self._devices[pin].is_active

    def all_off(self):
        for device in self._devices.values():
            device.off()

    def close(self):
        for device in self._devices.values():
            device.close()
        self._devices.clear()
        if self._owns_pin_factory and self._pin_factory is not None:
            self._pin_factory.close()
        self._pin_factory = None
