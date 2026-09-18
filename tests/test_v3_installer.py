import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-v3.sh"


class InstallerTests(unittest.TestCase):
    def test_installer_has_valid_bash_syntax_and_help(self):
        syntax = subprocess.run(
            ["bash", "-n", str(INSTALLER)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

        help_result = subprocess.run(
            ["bash", str(INSTALLER), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--mode http|https", help_result.stdout)
        self.assertIn("--valve-power-disconnected", help_result.stdout)

    def test_installer_defaults_to_the_tested_checkpoint(self):
        script = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('readonly DEFAULT_REF="v3-ui-checkpoint-2026-09-17"', script)
        self.assertIn('source_ref="${PI_SPRINKLER_REF:-${DEFAULT_REF}}"', script)

    def test_installer_preserves_configuration_and_secrets(self):
        script = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('if [[ ! -e "${CONFIGURATION_FILE}" ]]', script)
        self.assertIn('if [[ ! -s "${TOKEN_FILE}" ]]', script)
        self.assertIn('systemd-ask-password "Pi Sprinkler Timer API token', script)
        self.assertNotIn("set -x", script)
        self.assertNotIn('cat "${TOKEN_FILE}"', script)

    def test_installer_requires_relay_safety_confirmation_before_start(self):
        script = INSTALLER.read_text(encoding="utf-8")
        self.assertIn(
            'if [[ "${start_service}" == true && '
            '"${valve_power_disconnected}" != true ]]',
            script,
        )
        self.assertIn(
            'if [[ "${start_service}" == true ]]; then\n'
            '    log "Starting the controller with valve power confirmed disconnected"',
            script,
        )

    def test_installer_refuses_to_replace_unknown_paths_or_dirty_source(self):
        script = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("Source checkout has local changes", script)
        self.assertIn("Stop open-sprinkler-v3.service before installing", script)
        self.assertIn("Refusing to replace non-Git path", script)
        self.assertIn("Refusing to replace existing non-symlink", script)
        self.assertNotIn("rm -", script)


if __name__ == "__main__":
    unittest.main()
