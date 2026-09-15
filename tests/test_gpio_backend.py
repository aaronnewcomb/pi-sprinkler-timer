import unittest

from gpio_backend import RelayBank


class FakePinFactory:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeOutputDevice:
    instances = {}

    def __init__(self, pin, active_high, initial_value, pin_factory):
        self.pin = pin
        self.active_high = active_high
        self.value = initial_value
        self.pin_factory = pin_factory
        self.closed = False
        self.__class__.instances[pin] = self

    @property
    def is_active(self):
        return self.value

    def on(self):
        self.value = True

    def off(self):
        self.value = False

    def close(self):
        self.closed = True


class RelayBankTests(unittest.TestCase):
    def setUp(self):
        FakeOutputDevice.instances = {}
        self.pin_factory = FakePinFactory()
        self.relays = RelayBank(
            [5, 6],
            device_factory=FakeOutputDevice,
            pin_factory=self.pin_factory,
        )

    def tearDown(self):
        self.relays.close()

    def test_relays_are_active_low_and_initially_off(self):
        for device in FakeOutputDevice.instances.values():
            self.assertFalse(device.active_high)
            self.assertFalse(device.value)
            self.assertIs(device.pin_factory, self.pin_factory)

    def test_logical_on_off_and_status(self):
        self.relays.on(5)
        self.assertTrue(self.relays.is_on(5))
        self.assertFalse(self.relays.is_on(6))

        self.relays.off(5)
        self.assertFalse(self.relays.is_on(5))

    def test_all_off_deenergizes_every_relay(self):
        self.relays.on(5)
        self.relays.on(6)
        self.relays.all_off()
        self.assertFalse(self.relays.is_on(5))
        self.assertFalse(self.relays.is_on(6))

    def test_external_pin_factory_is_not_closed(self):
        devices = list(FakeOutputDevice.instances.values())
        self.relays.close()
        self.assertTrue(all(device.closed for device in devices))
        self.assertFalse(self.pin_factory.closed)


if __name__ == "__main__":
    unittest.main()
