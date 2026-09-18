# Legacy version 2 reference

Pi Sprinkler Timer 2.0 is preserved for existing installations and rollback.
Version 2 uses the original lighttpd CGI interface, a separate scheduler
daemon, and the legacy `sprinkler.config` format.

The exact source and installation instructions remain available in the
[`v2.0.0` release tag](https://github.com/aaronnewcomb/pi-sprinkler-timer/tree/v2.0.0).

To obtain that preserved version without mixing it with version 3:

```bash
git clone --branch v2.0.0 --single-branch \
    https://github.com/aaronnewcomb/pi-sprinkler-timer.git \
    pi-sprinkler-timer-v2
```

## Existing controllers

- Keep a known-working v2 boot card unchanged as a rollback.
- Back up `/var/www/html/cgi-bin/sprinkler.config` without committing it. It
  can contain deployment-specific settings or credentials.
- Do not run the version 3 installer on an old v2 operating-system image.
- Do not copy `sprinkler.config` over the version 3 INI configuration. The
  schemas and storage models are different.
- Keep the 24 VAC valve transformer disconnected while changing boot media or
  testing GPIO behavior.

Version 3 should be installed on fresh Raspberry Pi OS boot media by following
the [current installation guide](V3_INSTALLATION.md). Retain the original v2
media until version 3 has passed browser, schedule, service, and relay
acceptance on the live hardware.
