# Changelog

## 3.1.0, 2026-09-20

- Add a supervised schedule-test workflow that runs selected schedules in
  displayed order and overrides every included station to 30 seconds.
- Add persistent test progress, safe cancellation, and distinct
  `schedule-test` run-history records.
- Reject enabled schedule windows that overlap another enabled schedule or
  overlap themselves across selected days, including week-boundary and
  cross-midnight conflicts.
- Continue allowing disabled conflicting schedules to be drafted, while
  preventing them from being enabled until the conflict is resolved.
- Make `pi-sprinkler` the canonical package, executable, service, account,
  filesystem, proxy, browser-cookie, CSRF-header, and auxiliary-service
  namespace.
- Migrate v3.0 configuration, API token, SQLite state, TLS certificate, and
  local certificate authority while preserving the old paths for rollback.
- Extend controller readiness checks for Pi Zero startup, print actionable
  systemd diagnostics, and stop the controller safely if health never succeeds.

See the [full 3.1.0 release notes](docs/V3_1_RELEASE_NOTES.md) for installation,
upgrade, migration, and validation details.

## 3.0.0, 2026-09-19

Pi Sprinkler Timer 3.0 replaces the legacy CGI application with a local-first
controller, responsive dashboard, and versioned REST API.

### Highlights

- Manual station control with a live remaining-time countdown
- Editable multi-station schedules and SQLite run history
- Independent manual and automatic weather holds using Open-Meteo
- Current conditions and forecast information in the dashboard
- Web settings for station names, GPIO pins, timezone, safety limits, and Stop
  button behavior
- Bearer-authenticated REST API, signed browser sessions, and a Home Assistant
  starter configuration
- Automated HTTP or HTTPS installation with guided safety checks
- Optional systemd services for a physical shutdown button and an MQTT
  garage-door contact sensor
- GPIO Zero and `lgpio` relay control with serialized ownership and automatic
  shutoff

### Installation and migration

- Raspberry Pi OS Lite Trixie and Python 3.11 or newer are required.
- A clean operating-system image is recommended when replacing an old v2
  installation. Keep the old boot card unchanged for rollback.
- Disconnect the valve transformer during installation and startup-off checks.
  Turn on valve power only for supervised station-by-station acceptance.
- Install `git` and `ca-certificates` before cloning on a fresh image.
- The first installation on an original Raspberry Pi Zero can take about 15
  minutes.
- Existing v3 configuration, database, certificates, and API token are
  preserved when the installer is rerun.

See [the installation guide](docs/V3_INSTALLATION.md) for the complete procedure
and [the legacy v2 reference](docs/V2_INSTALLATION.md) for rollback information.
The [full 3.0.0 release notes](docs/V3_RELEASE_NOTES.md) include installation
commands and validation details.
