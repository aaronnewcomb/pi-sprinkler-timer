# Pi Sprinkler Timer

Pi Sprinkler Timer is a local-first irrigation controller for Raspberry Pi. It
provides a responsive web dashboard, scheduling, weather-aware holds, run
history, a versioned REST API, and Home Assistant integration.

GPIO Zero controls active-low relay boards through the `lgpio` backend. A
single systemd service owns every relay and automatically turns off manual runs
when their configured time expires.

> **Project status:** Version 3 is on the `develop/v3` branch and is undergoing
> final live-system acceptance. The proven `v2.0.0` release remains available
> as a rollback.

## Features

- Manual station control with a live remaining-time countdown
- Multi-station schedules with editing and local-time execution
- Independent manual rain holds and automatic weather holds
- Open-Meteo current conditions and precipitation forecasts
- SQLite schedule, settings, and run-history storage
- Editable station names, BCM GPIO pins, timezone, and safety limits
- Configurable dashboard Stop behavior
- Bearer-authenticated REST API and signed browser sessions
- Home Assistant REST sensors and commands
- Active-low relay safety, serialized GPIO ownership, and automatic shutoff

## Requirements

- Raspberry Pi supported by Raspberry Pi OS
- Raspberry Pi OS Lite Trixie, 32-bit or 64-bit
- Network connection
- Compatible active-low relay board
- 24 VAC sprinkler transformer and valves
- Python 3.11 or newer, installed automatically on Trixie

> **Relay safety:** Keep the valve transformer disconnected during installation
> and until every relay passes acceptance testing.

## Install version 3

The automated installer explains each stage, installs system packages and the
application, runs the test suite, creates the restricted service account,
configures lighttpd, collects the API token, and enables and starts the
controller. It installs the tested `v3-ui-checkpoint-2026-09-17` application
tag by default; use `--ref develop/v3` only for deliberate development testing.

Clone the installer bootstrap from the development branch:

```bash
git clone --branch develop/v3 --single-branch \
    https://github.com/aaronnewcomb/pi-sprinkler-timer.git \
    pi-sprinkler-installer
cd pi-sprinkler-installer
```

### Temporary HTTP acceptance

Use HTTP only for short acceptance testing on a trusted isolated LAN:

```bash
sudo ./scripts/install-v3.sh --mode http
```

The API token is unencrypted on the network in this mode.

### Private-LAN HTTPS

For regular use, provide the stable hostname and IP that the generated
certificate should cover:

```bash
sudo ./scripts/install-v3.sh --mode https \
    --hostname sprinkler.local --ip 192.168.0.50
```

The installer prompts for physical confirmation that valve power is
disconnected. For unattended use, `--valve-power-disconnected` can preconfirm
that condition only after the transformer has actually been disconnected.
Use `--no-start` for a deliberately staged installation.

The installer also explains how to generate and save the API token. Treat the
token like a password, keep it in a password manager, and retain it for browser
sign-in and Home Assistant. It is never printed by the installer.

See the [complete v3 installation and acceptance guide](docs/V3_INSTALLATION.md)
for HTTPS trust setup, troubleshooting, updates, and relay testing.

## Initial configuration and acceptance

After installation:

1. Open the web address printed by the installer and sign in with the saved API
   token.
2. Open **Settings** and verify every station name and BCM GPIO pin, the
   timezone, maximum run time, and Stop-button policy.
3. With valve power still disconnected, activate each station individually and
   confirm that only the intended relay turns on.
4. Switch directly between stations and confirm the previous relay turns off.
5. Create and edit a short schedule, then verify its run appears in history.
6. Configure weather automation if desired.
7. Review the service log and reconnect valve power only after all checks pass.

## Home Assistant

A starter REST configuration is provided in
[docs/home-assistant/rest.yaml](docs/home-assistant/rest.yaml). Store the full
Bearer authorization value in Home Assistant `secrets.yaml`; do not commit it
or paste it into chat.

The REST API is served under `/api/v1`. The web dashboard is one API client,
so browser and Home Assistant actions use the same controller and safety rules.

## Important paths

| Purpose | Path |
| --- | --- |
| Application source | `/opt/open-sprinkler/source` |
| Python environment | `/opt/open-sprinkler/.venv` |
| Controller configuration | `/etc/open-sprinkler/open-sprinkler.ini` |
| API token | `/etc/open-sprinkler/api-token` |
| Controller database | `/var/lib/open-sprinkler/open-sprinkler.db` |
| systemd service | `/etc/systemd/system/open-sprinkler-v3.service` |
| lighttpd proxy | `/etc/lighttpd/conf-available/99-open-sprinkler-v3.conf` |

Common service commands:

```bash
systemctl status open-sprinkler-v3.service --no-pager -l
sudo systemctl restart open-sprinkler-v3.service
journalctl -u open-sprinkler-v3.service -n 80 --no-pager
```

## Development

Version 3 requires Python 3.11 or newer. Use
[uv](https://docs.astral.sh/uv/) for a local development environment:

```bash
uv sync
uv run pytest
```

The suite covers the controller, scheduler, persistence, API, authentication,
weather automation, GPIO safety, web assets, deployment files, and installer.

## Documentation

- [Version 3 installation and acceptance](docs/V3_INSTALLATION.md)
- [Version 3 architecture and roadmap](docs/V3_ARCHITECTURE.md)
- [Home Assistant REST starter](docs/home-assistant/rest.yaml)
- [Legacy version 2 reference](docs/V2_INSTALLATION.md)

## Legacy version 2

Version 2 remains preserved at the `v2.0.0` tag for rollback and existing
installations. Do not run the v3 installer over an old production OS or
overwrite a working v2 boot card. See the
[legacy v2 reference](docs/V2_INSTALLATION.md).

## License

See [LICENSE](LICENSE).
