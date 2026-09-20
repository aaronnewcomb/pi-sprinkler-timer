# Pi Sprinkler Timer 3.0.0

Version 3.0.0 is a ground-up modernization of Pi Sprinkler Timer for current
Raspberry Pi OS releases. It replaces the legacy CGI application with a
local-first controller, responsive web dashboard, and versioned REST API.

## What is new

- Live manual-station countdowns and configurable run limits
- Editable multi-station schedules with SQLite persistence and run history
- Independent manual and automatic weather holds
- Open-Meteo current conditions and precipitation forecasts
- Web settings for station names, BCM GPIO pins, timezone, safety limits, and
  dashboard Stop behavior
- Bearer-authenticated API, signed browser sessions, and Home Assistant REST
  examples
- Guided HTTP or HTTPS installer with masked API-token collection
- Optional systemd services for a GPIO shutdown button and MQTT garage-door
  contact sensor
- A new Pi Zero and water-drop interface icon

## Platform and migration notes

- Raspberry Pi OS Lite Trixie and Python 3.11 or newer are required.
- Use a clean operating-system image when replacing an old v2 installation.
  Keep the old boot card unchanged for rollback.
- Disconnect the valve transformer during installation and startup-off checks.
  Turn on valve power only for supervised station-by-station acceptance.
- On a fresh image, install `git` and `ca-certificates` before cloning.
- Allow about 15 minutes for the first installation on an original Raspberry
  Pi Zero.
- Rerunning the installer preserves an existing v3 configuration, database,
  certificate pair, and valid API token.

## Installation

```bash
sudo apt update
sudo apt install -y git ca-certificates
git clone --branch v3.0.0 --single-branch \
    https://github.com/aaronnewcomb/pi-sprinkler-timer.git \
    pi-sprinkler-installer
cd pi-sprinkler-installer
sudo ./scripts/install-v3.sh --mode http
```

HTTP mode is intended only for temporary acceptance testing on a trusted LAN.
See the [complete installation guide](https://github.com/aaronnewcomb/pi-sprinkler-timer/blob/v3.0.0/docs/V3_INSTALLATION.md)
for private-LAN HTTPS, configuration, relay acceptance, and troubleshooting.

## Validation

- 88 automated tests passed
- 62 relay-safety subtests passed
- Python wheel and source distribution built successfully
- The GPIO shutdown-button and garage-door services were migrated to systemd
- The garage-door MQTT state path was verified on the original Raspberry Pi
  Zero and in Home Assistant

Version 2 remains available at the `v2.0.0` tag for legacy systems and rollback.
