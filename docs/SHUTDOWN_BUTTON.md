# Physical shutdown button

The legacy controller used a Python 2 listener launched from `rc.local` and a
SysV init script. The current replacement is a single systemd service using
Python 3, GPIO Zero, and the `lgpio` pin factory.

## Behavior

- The default input is **BCM GPIO 3**, physical pin 5, matching the old script.
- The input uses the Pi's pull-up and treats a button connection to ground as a
  press.
- GPIO Zero debounces the input for 0.2 seconds by default.
- A press requests `systemctl poweroff`, which lets systemd stop services in the
  normal order.
- Repeated callbacks cannot issue repeated poweroff requests.
- The listener runs as root because requesting a system poweroff is a privileged
  operation. The unit protects its files and cannot modify the sprinkler
  configuration.

## Install

From the checked-out repository on the new Raspberry Pi OS installation:

```bash
sudo ./scripts/install-shutdown-button.sh
```

The installer installs `python3-gpiozero` and `python3-lgpio`, validates the
unit, and enables and starts the service. If it finds the old listener, it:

1. Backs up `/etc/rc.local` and `/etc/init.d/pi_shutdown` under
   `/var/backups/open-sprinkler/`.
2. Comments only the known shutdown-button line in `rc.local`.
3. Disables the `pi_shutdown` SysV boot links.
4. Stops only the matching `/home/pi/scripts/shutdown.py` process.

The installer never changes sprinkler configuration, relay GPIO assignments,
or the sprinkler controller service.

Use `--no-start` to install and validate the unit without starting it. Use
`--pin BCM_PIN` to select a different BCM input. The effective values are kept
in `/etc/default/open-sprinkler-shutdown-button`.

Do not use `--keep-legacy` for a running migration unless the old listener has
already been stopped, because two processes must not own the same GPIO input.

## Service commands

```bash
systemctl status open-sprinkler-shutdown-button.service --no-pager -l
journalctl -u open-sprinkler-shutdown-button.service -n 50 --no-pager
sudo systemctl restart open-sprinkler-shutdown-button.service
```

Test with valve power disconnected. Pressing the button powers the Pi off, so
use the service status and journal for setup checks before testing the physical
button.
