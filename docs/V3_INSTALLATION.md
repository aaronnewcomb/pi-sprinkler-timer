# Open Sprinkler 3.0 test installation

This procedure prepares a separate Raspberry Pi 4 for 3.0 acceptance. Keep the
working 2.0 controller and its boot media unchanged. Version 3.0 must pass the
software, service, and relay tests below before valve power is connected.

The target image is Raspberry Pi OS Lite 64-bit Trixie. Use Raspberry Pi Imager
and new boot media rather than upgrading a Bookworm card in place. Configure the
hostname, user, network, timezone, and SSH access in Imager before first boot.

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
sudo apt install git lighttpd openssl python3 python3-venv python3-gpiozero python3-lgpio
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

Create the API token through a masked prompt. Use a password manager to provide
at least 32 characters, and do not paste the value into chat, shell arguments,
or the repository:

```bash
sudo install -m 0640 -o root -g open-sprinkler /dev/null \
    /etc/open-sprinkler/api-token
sudo systemd-ask-password "Open Sprinkler API token" | \
    sudo tee /etc/open-sprinkler/api-token >/dev/null
```

The same token can be stored in Home Assistant `secrets.yaml`. The browser
exchanges it for a signed, HttpOnly session and does not retain it in web
storage.

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

For browser sessions, install a certificate and private key trusted by your
devices, then adapt and enable `98-open-sprinkler-tls.conf.example`. Its HTTP
listener redirects every request to HTTPS so the API token is never submitted
over plain HTTP. Keep `secure_cookies = true` in the application
configuration. The TLS private key must remain root-owned and must never enter
Git.

For an isolated HTTP-only hardware test, `secure_cookies` may temporarily be
set to `false`. Do not use that setting on an untrusted network, and restore it
before production use.

Validate configuration before restarting the proxy:

```bash
sudo lighttpd -tt -f /etc/lighttpd/lighttpd.conf
sudo systemctl restart lighttpd
systemctl status lighttpd --no-pager -l
```

## 7. Software and relay acceptance

Disconnect the 24 VAC valve transformer. Start the application without
enabling it at boot:

```bash
sudo systemctl start open-sprinkler-v3.service
systemctl status open-sprinkler-v3.service --no-pager -l
journalctl -u open-sprinkler-v3.service -n 80 --no-pager
sudo ss -ltnp | grep ':8000'
```

The API must listen only on `127.0.0.1:8000`. Open the controller through
lighttpd, sign in, and confirm every station reports off. Test each relay
individually, switch directly between stations, set and clear a rain delay,
create a short schedule, and confirm its run appears in history.

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
