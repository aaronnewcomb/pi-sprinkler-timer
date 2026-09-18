# Pi Sprinkler Timer 3.0 test installation

This procedure prepares a separate Raspberry Pi 4 for 3.0 acceptance. Keep the
working 2.0 controller and its boot media unchanged. Version 3.0 must pass the
software, service, and relay tests below before valve power is connected.

The target image is Raspberry Pi OS Lite 64-bit Trixie. Use Raspberry Pi Imager
and new boot media rather than upgrading a Bookworm card in place. Configure the
hostname, user, network, timezone, and SSH access in Imager before first boot.

## Automated installation

The checked-in installer presents and explains eight stages: platform and
relay safety checks, operating-system packages, application installation,
automated tests, service account and credentials, the systemd unit, web
transport, and final activation. It defaults to the tested
`v3-ui-checkpoint-2026-09-17` tag and preserves an existing configuration,
database, certificate pair, and valid API token.

Bootstrap the installer from the development branch on a fresh Pi:

```bash
git clone --branch develop/v3 --single-branch \
    https://github.com/aaronnewcomb/pi-sprinkler-timer.git \
    pi-sprinkler-installer
cd pi-sprinkler-installer
```

For temporary HTTP acceptance on an isolated trusted LAN:

```bash
sudo ./scripts/install-v3.sh --mode http
```

For private-LAN HTTPS, provide the stable hostname and IP included in the
certificate:

```bash
sudo ./scripts/install-v3.sh --mode https \
    --hostname sprinkler.local --ip 192.168.0.50
```

Before running the installer, use a password manager to generate and save a
unique random token containing at least 32 characters. A length of 40 to 64
characters is recommended. Label it with the controller hostname or IP. The
same token signs in to the browser dashboard and authenticates Home Assistant,
so the saved copy is needed after installation.

The installer explains these steps, waits for confirmation that the token is
saved, and then collects it through a masked system prompt. The prompt has no
time limit and the token is never printed. If the installer is interrupted at
this step, rerun the same command. Existing completed work is reused, and an
empty or incomplete token file is safely replaced by a new prompt.

By default the installer explains the relay-safety requirement, asks you to
confirm that the 24 VAC valve transformer is disconnected, then enables and
starts both lighttpd and `open-sprinkler-v3.service`. It verifies the service
state and application health endpoint before reporting completion. Keep valve
power disconnected until relay acceptance passes.

For unattended automation, the physical safety check can be preconfirmed only
after disconnecting valve power:

```bash
sudo ./scripts/install-v3.sh --mode http \
    --valve-power-disconnected
```

Use `--no-start` only when deliberately staging the files while leaving the
controller service disabled and stopped.

Use `--ref develop/v3` only when deliberately testing development beyond the
checkpoint. Run `./scripts/install-v3.sh --help` for all options. The detailed
manual steps below remain the troubleshooting, audit, and relay-acceptance
reference. On an existing installation, stop `open-sprinkler-v3.service`
before rerunning the installer; it refuses to modify a live controller.

## 1. Inspect the fresh system

```bash
cat /proc/device-tree/model
cat /etc/os-release
uname -r
python3 --version
groups
getent group gpio
```

Confirm the machine is the separate test Pi, the OS reports Trixie, and the
test user belongs to the `gpio` group.

## 2. Install system packages

```bash
sudo apt update
sudo apt full-upgrade
sudo apt install git lighttpd lighttpd-mod-openssl openssl python3 python3-venv \
    python3-gpiozero python3-lgpio
sudo reboot
```

After reconnecting, confirm no old controller owns the relays or legacy port:

```bash
systemctl is-active pigpiod.service || true
sudo ss -ltnp | grep ':5555' || echo "Legacy port 5555 is free"
pgrep -af 'sprinkler.py|open-sprinkler' || true
```

## 3. Install the application in an isolated environment

```bash
sudo install -d -m 0755 -o root -g root /opt/open-sprinkler
sudo git clone --branch develop/v3 --single-branch \
    https://github.com/aaronnewcomb/pi-sprinkler-timer.git \
    /opt/open-sprinkler/source
sudo python3 -m venv --system-site-packages /opt/open-sprinkler/.venv
sudo /opt/open-sprinkler/.venv/bin/pip install /opt/open-sprinkler/source
```

The virtual environment isolates FastAPI and Uvicorn while retaining access to
the GPIO Zero and lgpio packages installed by APT.

Run the complete suite before creating the service account:

```bash
cd /opt/open-sprinkler/source
sudo /opt/open-sprinkler/.venv/bin/pip install pytest httpx
sudo /opt/open-sprinkler/.venv/bin/pytest -q
```

## 4. Create the service account and configuration

```bash
sudo useradd --system --user-group --home-dir /var/lib/open-sprinkler \
    --shell /usr/sbin/nologin open-sprinkler
sudo usermod --append --groups gpio open-sprinkler
sudo install -d -m 0750 -o root -g open-sprinkler /etc/open-sprinkler
sudo install -m 0640 -o root -g open-sprinkler \
    /opt/open-sprinkler/source/open-sprinkler-v3.ini.example \
    /etc/open-sprinkler/open-sprinkler.ini
sudoedit /etc/open-sprinkler/open-sprinkler.ini
```

Keep the server bound to `127.0.0.1`. Verify the BCM GPIO numbers, station
names, `America/Los_Angeles` timezone, and database path.

The `[Weather]` polling interval defaults to 900 seconds. Location,
precipitation threshold, and post-precipitation delay are stored in SQLite and
configured later from the browser, so they do not belong in this root-managed
file.

Create the API token through a masked prompt. First use a password manager to
generate and save a unique random password containing at least 32 characters;
40 to 64 characters is recommended. Label it with the controller hostname or
IP. Do not paste the value into chat, shell arguments, or the repository:

```bash
sudo install -m 0640 -o root -g open-sprinkler /dev/null \
    /etc/open-sprinkler/api-token
sudo systemd-ask-password --timeout=0 "Paste the saved API token" | \
    sudo tee /etc/open-sprinkler/api-token >/dev/null
```

The same saved token can be stored in Home Assistant `secrets.yaml`. The
browser exchanges it for a signed, HttpOnly session and does not retain it in
web storage. The prompt waits indefinitely; press Ctrl+C if you need to stop
and repeat these token-creation commands later.

## 5. Install the service without starting it

```bash
sudo install -m 0644 /opt/open-sprinkler/source/systemd/open-sprinkler-v3.service \
    /etc/systemd/system/open-sprinkler-v3.service
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/open-sprinkler-v3.service
systemctl is-enabled open-sprinkler-v3.service
systemctl is-active open-sprinkler-v3.service
```

It must remain disabled and inactive until valve power is disconnected.

## 6. Configure lighttpd and TLS

Install the reverse proxy configuration:

```bash
sudo install -m 0644 /opt/open-sprinkler/source/lighttpd/99-open-sprinkler-v3.conf \
    /etc/lighttpd/conf-available/99-open-sprinkler-v3.conf
sudo ln -s ../conf-available/99-open-sprinkler-v3.conf \
    /etc/lighttpd/conf-enabled/99-open-sprinkler-v3.conf
```

Choose one of the following browser-access paths before starting the service.

### Option A: temporary HTTP for isolated hardware acceptance

For an isolated test on a trusted LAN, edit
`/etc/open-sprinkler/open-sprinkler.ini` and temporarily set:

```ini
secure_cookies = false
```

Do not enable the TLS example in this mode. Open the controller with
`http://CONTROLLER-IP/`. The API token travels over the local network without
encryption, so use this only for short hardware acceptance on a trusted LAN.
Use a temporary token, then rotate it and restore `secure_cookies = true`
before regular use.

### Option B: trusted HTTPS for private-LAN use

The commands below use `mkcert` to create a private certificate authority and
a server certificate. Replace the example name and address with the stable
hostname and IP address of this Pi. If `hostname` prints `opensprinkler`, the
mDNS name is normally `opensprinkler.local`.

```bash
hostname
hostname -I

sprinkler_name="opensprinkler.local"
sprinkler_ip="192.168.0.50"

sudo apt install mkcert libnss3-tools lighttpd-mod-openssl
mkcert -install

sudo install -d -m 0700 -o root -g root \
    /etc/lighttpd/certs/open-sprinkler
sudo env CAROOT="$(mkcert -CAROOT)" mkcert \
    -cert-file /etc/lighttpd/certs/open-sprinkler/fullchain.pem \
    -key-file /etc/lighttpd/certs/open-sprinkler/privkey.pem \
    "$sprinkler_name" "$sprinkler_ip"
sudo chmod 0644 /etc/lighttpd/certs/open-sprinkler/fullchain.pem
sudo chmod 0600 /etc/lighttpd/certs/open-sprinkler/privkey.pem
```

Inspect the certificate without displaying the private key:

```bash
sudo openssl x509 \
    -in /etc/lighttpd/certs/open-sprinkler/fullchain.pem \
    -noout -subject -issuer -dates -ext subjectAltName
```

Install the TLS configuration:

```bash
sudo test ! -e /etc/lighttpd/conf-available/98-open-sprinkler-tls.conf
sudo install -m 0644 \
    /opt/open-sprinkler/source/lighttpd/98-open-sprinkler-tls.conf.example \
    /etc/lighttpd/conf-available/98-open-sprinkler-tls.conf
sudo ln -s ../conf-available/98-open-sprinkler-tls.conf \
    /etc/lighttpd/conf-enabled/98-open-sprinkler-tls.conf
```

`mkcert -install` trusts the new certificate authority on the Pi only. Run
`mkcert -CAROOT` to locate `rootCA.pem`, then transfer only that public CA
certificate to each computer, phone, or tablet that will open the controller
and install it as a trusted CA. Never copy or share `rootCA-key.pem`; possession
of that private key permits issuing certificates trusted by those devices.

Keep `secure_cookies = true` in the application configuration. The HTTP
listener redirects every request to HTTPS so the API token is not submitted
over plain HTTP. The server private key must remain root-owned and must never
enter Git.

Validate configuration before restarting the proxy:

```bash
sudo lighttpd -tt -f /etc/lighttpd/lighttpd.conf
sudo systemctl restart lighttpd
systemctl status lighttpd --no-pager -l
```

For Option B, verify the redirect and TLS handshake before the application is
started:

```bash
curl -I "http://${sprinkler_ip}/"
openssl s_client -brief -verify_return_error \
    -connect "${sprinkler_ip}:443" \
    -servername "$sprinkler_name" \
    -CAfile "$(mkcert -CAROOT)/rootCA.pem" </dev/null
```

The redirect must point to HTTPS, and the TLS output must report successful
certificate verification. A proxy error at this point is expected because the
application service remains stopped.

## 7. Software and relay acceptance

Disconnect the 24 VAC valve transformer. Start the application without
enabling it at boot:

```bash
sudo systemctl start open-sprinkler-v3.service
systemctl status open-sprinkler-v3.service --no-pager -l
journalctl -u open-sprinkler-v3.service -n 80 --no-pager
sudo ss -ltnp | grep ':8000'
curl --fail --show-error http://127.0.0.1/
```

The API must listen only on `127.0.0.1:8000`, and the lighttpd request must
return the Pi Sprinkler Timer page. Open the controller from another computer at
`http://CONTROLLER-IP/` for Option A or `https://CONTROLLER-IP/` for Option B.
Sign in and confirm every station reports off. Test each relay individually,
switch directly between stations, confirm the active station displays a live
countdown, set and clear both preset and custom rain delays, create a short
schedule, and confirm its run appears in history.

Open **Settings**, verify the station names, BCM GPIO pins, timezone, maximum
run time, and Stop-button policy, then save. Changes other than GPIO pins apply
immediately. If the page reports that a GPIO restart is required, disconnect
valve power, restart `open-sprinkler-v3.service`, verify all relays remain off,
and reconnect valve power only after testing each station. Create a schedule,
use **Edit** to change it, and confirm the updated values survive a page reload.

If weather automation will be used, open **Settings**, enable it, and provide a
ZIP or postal code or latitude and longitude. Set the precipitation threshold
in inches and the number of hours to hold schedules after the last expected
precipitation. Confirm the navigation shows current conditions and future rain
probability, then confirm a qualifying forecast appears as a weather hold in
the controller-status box. The Pi must be able to resolve and reach
`api.open-meteo.com` and `geocoding-api.open-meteo.com` over HTTPS. No provider
credential is stored by Pi Sprinkler Timer. Weather data is provided by
[Open-Meteo](https://open-meteo.com/).

For Option B, the health endpoint must now succeed:

```bash
curl --fail --show-error "https://${sprinkler_ip}/api/v1/health"
```

Stop the service and confirm every relay remains off:

```bash
sudo systemctl stop open-sprinkler-v3.service
systemctl is-active open-sprinkler-v3.service
sudo ss -ltnp | grep ':8000' || echo "API port 8000 released"
journalctl -u open-sprinkler-v3.service -n 80 --no-pager
```

Only after all checks pass should the service be enabled and valve power be
reconnected:

```bash
sudo systemctl enable --now open-sprinkler-v3.service
```
