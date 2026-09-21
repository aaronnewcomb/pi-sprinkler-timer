import importlib.util
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "garage_door_monitor.py"
INSTALLER = ROOT / "scripts" / "install-garage-door-monitor.sh"
UNIT = ROOT / "systemd" / "pi-sprinkler-garage-door.service"


def load_module():
    spec = importlib.util.spec_from_file_location("garage_door_monitor", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def module():
    return load_module()


@pytest.fixture
def config(module):
    return module.GarageDoorConfig(
        gpio_pin=4,
        bounce_time=0.1,
        mqtt_host="mqtt.local",
        mqtt_port=1883,
        mqtt_username="user",
        mqtt_password="password",
        mqtt_topic="toggle/garage_door/state",
        open_payload="ON",
        closed_payload="OFF",
        retain=False,
        retry_seconds=0.01,
    )


class FakeInput:
    def __init__(self, active=False):
        self.is_active = active
        self.when_activated = None
        self.when_deactivated = None
        self.closed = False

    def close(self):
        self.closed = True


class FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, *, retain):
        self.messages.append((topic, payload, retain))


def test_open_and_closed_payloads_preserve_legacy_semantics(module, config):
    input_device = FakeInput(active=False)
    publisher = FakePublisher()
    monitor = module.GarageDoorMonitor(input_device, publisher, config)

    assert monitor.publish_current()
    assert not monitor.publish_current()
    input_device.is_active = True
    assert monitor.publish_current()

    assert publisher.messages == [
        ("toggle/garage_door/state", "ON", False),
        ("toggle/garage_door/state", "OFF", False),
    ]


def test_run_publishes_initial_state(module, config):
    input_device = FakeInput(active=False)
    publisher = FakePublisher()
    monitor = module.GarageDoorMonitor(input_device, publisher, config)
    stop_event = threading.Event()

    def publish_and_stop(topic, payload, *, retain):
        publisher.messages.append((topic, payload, retain))
        stop_event.set()

    publisher.publish = publish_and_stop
    monitor.run(stop_event)

    assert publisher.messages == [("toggle/garage_door/state", "ON", False)]


def test_run_retries_failed_publish(module, config):
    input_device = FakeInput(active=False)
    stop_event = threading.Event()
    attempts = []

    class FlakyPublisher:
        def publish(self, topic, payload, *, retain):
            attempts.append((topic, payload, retain))
            if len(attempts) == 1:
                raise OSError("broker unavailable")
            stop_event.set()

    monitor = module.GarageDoorMonitor(input_device, FlakyPublisher(), config)
    monitor.run(stop_event)

    assert attempts == [
        ("toggle/garage_door/state", "ON", False),
        ("toggle/garage_door/state", "ON", False),
    ]


def test_config_rejects_partial_credentials(module, tmp_path):
    path = tmp_path / "garage-door.ini"
    path.write_text(
        """[garage-door]
mqtt_host = mqtt.local
mqtt_username = user
mqtt_topic = garage/state
"""
    )

    with pytest.raises(ValueError, match="must both be set"):
        module.load_config(path)


def test_config_defaults_match_recovered_installation(module, tmp_path):
    path = tmp_path / "garage-door.ini"
    path.write_text(
        """[garage-door]
mqtt_host = 192.168.0.3
mqtt_topic = toggle/garage_door/state
"""
    )

    loaded = module.load_config(path)

    assert loaded.gpio_pin == 4
    assert loaded.mqtt_port == 1883
    assert loaded.open_payload == "ON"
    assert loaded.closed_payload == "OFF"
    assert loaded.retain is False


def test_check_config_does_not_require_gpio_or_mqtt(tmp_path):
    path = tmp_path / "garage-door.ini"
    path.write_text(
        """[garage-door]
mqtt_host = mqtt.local
mqtt_topic = garage/state
"""
    )

    result = subprocess.run(
        ["python3", str(SCRIPT), "--config", str(path), "--check-config"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "configuration is valid" in result.stderr


def test_service_is_hardened_and_uses_dedicated_account():
    unit = UNIT.read_text()
    assert "User=garage-door-monitor" in unit
    assert "SupplementaryGroups=gpio" in unit
    assert "RuntimeDirectory=pi-sprinkler-garage-door" in unit
    assert "WorkingDirectory=/run/pi-sprinkler-garage-door" in unit
    assert "After=network-online.target" in unit
    assert "/etc/pi-sprinkler-garage-door/garage-door.ini" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "WantedBy=multi-user.target" in unit


def test_installer_protects_credentials_and_disables_legacy_listener():
    installer = INSTALLER.read_text()
    assert "python3-paho-mqtt" in installer
    assert 'systemd-ask-password --timeout=0 "Garage door MQTT username:"' in installer
    assert 'systemd-ask-password --timeout=0 "Garage door MQTT password:"' in installer
    assert "mqtt-password" not in installer
    assert "install -m 0640" in installer
    assert "already assigned to a sprinkler station" in installer
    assert "already assigned to the shutdown button" in installer
    assert "LEGACY_SPRINKLER_CONFIG_FILE" in installer
    assert "LEGACY_SHUTDOWN_DEFAULTS_FILE" in installer
    assert 'parser.get("Station GPIOs", "pins"' in installer
    assert "--check-config" in installer
    assert "systemctl disable --now reed_switch.service" in installer
    assert "legacy reed-switch process is still running" in installer
    assert "systemctl enable --now" in installer


def test_script_compiles_and_installer_has_valid_shell_syntax():
    compile_result = subprocess.run(
        ["python3", "-m", "py_compile", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    shell_result = subprocess.run(
        ["bash", "-n", str(INSTALLER)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert shell_result.returncode == 0, shell_result.stderr
