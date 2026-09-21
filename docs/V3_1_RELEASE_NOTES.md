# Pi Sprinkler Timer 3.1.0

Version 3.1 adds supervised schedule testing, prevents conflicting schedule
windows, and completes the deployment rename from the historical
`open-sprinkler` namespace to `pi-sprinkler`.

## What is new

- Select one or more schedules in the dashboard and test them in displayed
  order, with each included station limited to a supervised 30-second run.
- View persistent test progress, stop the test safely, and distinguish test
  activity from normal schedule runs in history.
- Reject enabled schedules whose complete run windows overlap on a shared day,
  including conflicts that cross midnight or the weekly boundary.
- Keep disabled conflicting schedules available as drafts while preventing
  them from being enabled until the conflict is resolved.
- Use `pi-sprinkler` consistently for the Python package, command, systemd
  services, service account, configuration, state, proxy, browser cookie, CSRF
  header, and optional GPIO services.
- Allow up to 90 seconds for controller readiness on a loaded Pi Zero, report
  detailed systemd diagnostics on failure, and stop the unhealthy controller
  rather than leaving it active.

## Upgrade from version 3.0

The 3.1 installer migrates the existing controller configuration, API token,
SQLite schedules and history, TLS certificate, and local certificate authority
to the new `pi-sprinkler` paths. It disables and archives obsolete unit and
lighttpd files under `/var/backups/pi-sprinkler/name-migration/`. The old
application, configuration, state, and certificate directories remain intact
as rollback data.

An installer checkout cloned with `--branch v3.0.0 --single-branch` must fetch
the new release tag before it can run the 3.1 migration logic:

```bash
cd ~/pi-sprinkler-installer
git fetch origin tag v3.1.0
git switch --detach v3.1.0
git describe --tags --exact-match
sudo systemctl stop open-sprinkler-v3.service
sudo ./scripts/install-v3.sh --mode http
```

Use the same HTTPS hostname and IP options as the existing installation when
upgrading an HTTPS controller. Keep valve power disconnected during the
installer's startup verification. Browser sessions use the new cookie
namespace, so sign in again with the existing saved API token afterward. Home
Assistant entity and action names already use `pi_sprinkler` and do not change.

## Fresh installation

```bash
sudo apt update
sudo apt install -y git ca-certificates
git clone --branch v3.1.0 --single-branch \
    https://github.com/aaronnewcomb/pi-sprinkler-timer.git \
    pi-sprinkler-installer
cd pi-sprinkler-installer
sudo ./scripts/install-v3.sh --mode http
```

HTTP mode is intended only for temporary acceptance testing on a trusted LAN.
See the [complete installation guide](https://github.com/aaronnewcomb/pi-sprinkler-timer/blob/v3.1.0/docs/V3_INSTALLATION.md)
for private-LAN HTTPS, migration details, relay acceptance, and troubleshooting.

## Validation

- 100 automated tests passed
- 62 relay-safety subtests passed
- Ruff, shell syntax, JavaScript syntax, and documentation link checks passed
- Python wheel and source distribution built successfully
- Desktop and mobile schedule-test flows passed against a fake relay controller
- The 3.1 development build was accepted on the live Pi Sprinkler system

Version 3.0 remains available at the `v3.0.0` tag as a rollback point. Version
2 remains available at `v2.0.0` for legacy systems.
