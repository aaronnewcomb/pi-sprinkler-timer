import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "shutdown_button.py"
INSTALLER = ROOT / "scripts" / "install-shutdown-button.sh"
UNIT = ROOT / "systemd" / "open-sprinkler-shutdown-button.service"


def load_module():
    spec = importlib.util.spec_from_file_location("shutdown_button", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeButton:
    def __init__(self):
        self.when_pressed = None
        self.closed = False

    def close(self):
        self.closed = True

    def press(self):
        self.when_pressed()


def test_button_requests_poweroff_once_until_failure():
    module = load_module()
    button = FakeButton()
    calls = []

    def runner(command, check):
        calls.append((command, check))
        return subprocess.CompletedProcess(command, 0)

    module.ShutdownListener(button, shutdown_runner=runner)
    button.press()
    button.press()

    assert calls == [(module.POWER_OFF_COMMAND, False)]


def test_failed_poweroff_can_be_retried():
    module = load_module()
    button = FakeButton()
    outcomes = iter([1, 0])
    calls = []

    def runner(command, check):
        calls.append(command)
        return subprocess.CompletedProcess(command, next(outcomes))

    module.ShutdownListener(button, shutdown_runner=runner)
    button.press()
    button.press()

    assert calls == [module.POWER_OFF_COMMAND, module.POWER_OFF_COMMAND]


def test_shutdown_button_unit_is_hardened_and_boot_enabled():
    unit = UNIT.read_text()
    assert "User=root" in unit
    assert "ExecStart=/usr/bin/python3 /usr/local/libexec/open-sprinkler-shutdown-button.py" in unit
    assert "EnvironmentFile=-/etc/default/open-sprinkler-shutdown-button" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "WantedBy=multi-user.target" in unit


def test_shutdown_button_installer_has_legacy_migration_guard():
    installer = INSTALLER.read_text()
    assert "python3-gpiozero python3-lgpio" in installer
    assert "rc.local" in installer
    assert "update-rc.d pi_shutdown disable" in installer
    assert "legacy listener did not stop" in installer
    assert "systemctl enable --now" in installer


def test_shutdown_button_script_compiles():
    result = subprocess.run(
        ["python3", "-m", "py_compile", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
