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
        self.assertIn("--no-start", help_result.stdout)
        self.assertIn("--valve-power-disconnected", help_result.stdout)

    def test_installer_defaults_to_the_tested_checkpoint(self):
        script = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('readonly DEFAULT_REF="v3.0.0"', script)
        self.assertIn('source_ref="${PI_SPRINKLER_REF:-${DEFAULT_REF}}"', script)

    def test_installer_preserves_configuration_and_secrets(self):
        script = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('if [[ ! -e "${CONFIGURATION_FILE}" ]]', script)
        self.assertIn("if ! token_is_valid; then", script)
        self.assertIn("raise SystemExit(0 if len(token) >= 32 else 1)", script)
        self.assertNotIn("set -x", script)
        self.assertNotIn('cat "${TOKEN_FILE}"', script)

    def test_token_prompt_explains_storage_and_has_no_timeout(self):
        script = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("Use your password manager to generate", script)
        self.assertIn("at least 32 characters", script)
        self.assertIn("future browser logins and Home Assistant setup", script)
        self.assertIn("systemd-ask-password --timeout=0", script)
        self.assertIn("rerun the installer to resume", script)

    def test_installer_explains_each_installation_stage(self):
        script = INSTALLER.read_text(encoding="utf-8")
        expected_titles = (
            "Safety and platform checks",
            "Operating-system packages",
            "Application and Python environment",
            "Automated software tests",
            "Service account, configuration, and API token",
            "systemd controller service",
            "Web proxy and transport security",
            "Controller activation and health verification",
        )
        for number, title in enumerate(expected_titles, start=1):
            self.assertIn(f'stage {number} 8 "{title}"', script)

    def test_installer_enables_service_after_relay_safety_confirmation(self):
        script = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("start_service=true", script)
        self.assertIn(
            'read -r -p "Type DISCONNECTED to confirm valve power is disconnected: "',
            script,
        )
        self.assertIn('[[ "${relay_confirmation}" == "DISCONNECTED" ]]', script)
        self.assertIn(
            'if [[ "${start_service}" == true ]]; then\n'
            '    [[ "${valve_power_disconnected}" == true ]]',
            script,
        )
        self.assertIn(
            'systemctl enable --now "${SERVICE_NAME}"',
            script,
        )
        self.assertIn(
            'systemctl disable --now "${SERVICE_NAME}"',
            script,
        )
        self.assertNotIn("Next steps:", script)

    def test_installer_refuses_to_replace_unknown_paths_or_dirty_source(self):
        script = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("Source checkout has local changes", script)
        self.assertIn("The controller service ${controller_service} is active", script)
        self.assertIn(
            "sudo systemctl stop ${controller_service}",
            script,
        )
        self.assertIn("Refusing to replace non-Git path", script)
        self.assertIn("Refusing to replace existing non-symlink", script)
        self.assertNotIn("rm -", script)

    def test_installer_migrates_v3_legacy_names_without_losing_state(self):
        script = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('readonly SERVICE_NAME="pi-sprinkler.service"', script)
        self.assertIn('"open-sprinkler-v3.service"', script)
        self.assertIn('"open-sprinkler.service"', script)
        self.assertIn("migrate_legacy_controller_data", script)
        self.assertIn("source.backup(destination)", script)
        self.assertIn('token_is_valid "${LEGACY_TOKEN_FILE}"', script)
        self.assertIn("Migrating the existing TLS certificate", script)
        self.assertIn("Migrating the existing local certificate authority", script)
        self.assertIn("retire_legacy_controller_units", script)
        self.assertIn("retire_legacy_lighttpd_configuration", script)
        self.assertIn("/var/backups/pi-sprinkler/name-migration", script)

    def test_installer_allows_slow_startup_and_reports_health_failures(self):
        script = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("readonly CONTROLLER_HEALTH_TIMEOUT_SECONDS=90", script)
        self.assertIn('systemctl is-failed --quiet "${SERVICE_NAME}"', script)
        self.assertIn(
            "--property=ActiveState,SubState,Result,NRestarts,ExecMainCode,ExecMainStatus",
            script,
        )
        self.assertIn('journalctl -u "${SERVICE_NAME}" -n 80', script)
        self.assertIn(
            'fail "${reason}; ${SERVICE_NAME} was stopped and disabled"', script
        )
        self.assertNotIn("within 20 seconds", script)


if __name__ == "__main__":
    unittest.main()
