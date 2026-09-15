# Installation findings

This file records differences discovered while installing the modernization
branch on current Raspberry Pi OS. Each item remains here until its final
documentation or code change is verified on target hardware.

## Test environment

- Raspberry Pi 4 Model B Rev 1.2
- Debian Bookworm 12 with Raspberry Pi kernel `6.12.25+rpt-rpi-v8`
- Python 3.11.2
- Branch `modernize/gpiozero-systemd`
- The test user belongs to the `gpio` group
- `pigpiod` is installed but disabled and inactive
- TCP port 5555 was free before installation
- The 24 VAC valve transformer remained disconnected

## Findings

### Python 3.11 requires `type_ignores` on synthetic AST modules

- **Expected:** All 16 tests pass under the target Python interpreter.
- **Observed:** Two protocol tests failed with `TypeError: required field
  "type_ignores" missing from Module`.
- **Impact:** Test-only compatibility issue. Application and GPIO code were
  unaffected.
- **Resolution:** Added a runtime-aware AST module constructor in commit
  `631c115`.
- **Verification:** All 16 tests passed under Python 3.11 locally and on the
  test Pi.
- **README impact:** State that the complete suite must be run on the target
  Pi, not only on a development machine.

### Bookworm uses a shebang-based CGI handler

- **Expected:** `/etc/lighttpd/conf-enabled/10-cgi.conf` contains an explicit
  `.py` to `/usr/bin/python3` mapping.
- **Observed:** Bookworm configures `cgi.assign = ( "" => "" )` for
  `/cgi-bin/`, so executable scripts run through their own shebang.
- **Impact:** The Python 3 scripts are compatible, but the README's explicit
  mapping check was incorrect for this packaged configuration.
- **Resolution:** Rely on the existing `#!/usr/bin/python3` shebangs and
  executable file permissions.
- **Verification:** Configuration content confirmed on the test Pi. CGI
  execution remains to be tested after deployment.
- **README impact:** Explain both supported handler styles and verify the
  enabled CGI configuration rather than requiring one exact mapping.

### Bookworm aliases `/cgi-bin/` to `/usr/lib/cgi-bin/`

- **Expected:** Application scripts installed in `/var/www/html/cgi-bin/`
  are served at `/cgi-bin/`.
- **Observed:** The packaged `10-cgi.conf` aliases `/cgi-bin/` to
  `/usr/lib/cgi-bin/`.
- **Impact:** The existing deployment instructions and systemd paths would
  install and start code from a directory lighttpd does not serve.
- **Resolution:** Install scripts and runtime configuration under
  `/usr/lib/cgi-bin/`, update the service paths, and derive the configuration
  path from each script's installed directory.
- **Verification:** All 17 tests pass under the development Python, an exact
  Python 3.11 interpreter, and the test Pi's Python 3.11.2 runtime.
  `systemd-analyze verify` accepts the unit. CGI execution remains to be
  tested on the Pi.
- **README impact:** Use the Raspberry Pi OS packaged CGI directory or clearly
  document a custom alias when another path is selected.

### Plaintext lighttpd password storage should not be used

- **Expected:** The original README uses `auth.backend = "plain"` and stores
  `username:password` directly in a file.
- **Observed:** Current lighttpd documentation identifies the plain backend as
  cleartext storage.
- **Impact:** Following the original instructions would leave a reusable
  password readable on disk.
- **Proposed resolution:** Use a masked `htdigest` prompt and a root-owned file
  readable by the `www-data` group. Add HTTPS in a later hardening round.
- **Verification:** Digest authentication configuration validates without
  warnings after explicitly loading `mod_authn_file`, and lighttpd is active
  on the test Pi. Browser authentication remains to be tested after CGI
  deployment.
- **README impact:** Replace the plaintext backend instructions and warn that
  authentication without HTTPS is suitable only for a trusted test network.

### The htdigest backend requires an explicit `mod_authn_file` module

- **Expected:** Enabling lighttpd's packaged `auth` module is sufficient for
  an `auth.backend = "htdigest"` site configuration.
- **Observed:** Configuration validation succeeded but warned that a future
  lighttpd 1.4.x release will stop automatically loading `mod_authn_file`.
- **Impact:** Authentication works now, but a future lighttpd update could
  prevent the service from starting.
- **Resolution:** Add `server.modules += ( "mod_authn_file" )` before the
  htdigest backend settings in the Open Sprinkler configuration.
- **Verification:** `lighttpd -tt` completes without output, the warning is
  gone, and lighttpd restarts successfully on the test Pi.
- **README impact:** Include the explicit authentication backend module in the
  site configuration example.
