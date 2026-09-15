# pi-sprinkler-timer
A DIY web-driven scheduler for Raspberry Pi OS, written in Python 3 and served by lighttpd. GPIO Zero controls active-low relay boards through the `lgpio` backend. The scheduler runs as a systemd service.

(If you are looking for a more turnkey and feature rich solution for your RPi, I highly recommend [OpenSprinkler Pi](https://opensprinkler.com/product/opensprinkler-pi/) instead.)

## Parts
* Raspberry Pi
 * Network connection
 * Power Supply for RPi
* 24V AC Sprinkler Power Supply
* Sprinkler Valves
* 5V Relay Board

## Prerequisites

Use a current Raspberry Pi OS release. Install the web server, Python 3, GPIO Zero, and the `lgpio` pin library from APT:

```bash
sudo apt update
sudo apt install lighttpd apache2-utils python3 python3-gpiozero python3-lgpio
```

GPIO access is performed only by the scheduler service. The CGI scripts send commands to that service over a loopback-only TCP socket.

## Installation
### Configure lighttpd to run Python scripts with password protection

#### 1. Enable the CGI and authentication modules

```bash
sudo lighty-enable-mod cgi
sudo lighty-enable-mod auth
```

On Raspberry Pi OS Bookworm, the packaged CGI configuration maps `/cgi-bin/` to `/usr/lib/cgi-bin/` and uses each executable script's Python 3 shebang.

#### 2. Create a digest authentication file

Check that the target is new because `htdigest -c` creates or replaces the file:

```bash
sudo test ! -e /etc/lighttpd/open-sprinkler.htdigest
sudo htdigest -c /etc/lighttpd/open-sprinkler.htdigest "Open Sprinkler" admin
sudo chown root:www-data /etc/lighttpd/open-sprinkler.htdigest
sudo chmod 640 /etc/lighttpd/open-sprinkler.htdigest
```

Enter the password only at the masked terminal prompts. Do not store it in this repository or in shell history.

#### 3. Protect the CGI directory

Create `/etc/lighttpd/conf-available/99-open-sprinkler.conf` with:

```lighttpd
auth.backend = "htdigest"
auth.backend.htdigest.userfile = "/etc/lighttpd/open-sprinkler.htdigest"

auth.require = (
    "/cgi-bin/" => (
        "method"  => "digest",
        "realm"   => "Open Sprinkler",
        "require" => "user=admin"
    )
)
```

Enable the configuration:

```bash
sudo ln -s ../conf-available/99-open-sprinkler.conf \
    /etc/lighttpd/conf-enabled/99-open-sprinkler.conf
```

#### 4. Validate and restart lighttpd

```bash
sudo lighttpd -tt -f /etc/lighttpd/lighttpd.conf
sudo systemctl restart lighttpd
systemctl status lighttpd --no-pager
```

### Copy the application

Clone the repository, then install the web files. Raspberry Pi OS maps `/cgi-bin/` to `/usr/lib/cgi-bin/`, which is also the path expected by the included service:

```bash
sudo install -m 0755 -o root -g root ./*.py /usr/lib/cgi-bin/
sudo install -m 0644 -o www-data -g www-data index.html /var/www/html/index.html
```

Create the runtime configuration. This separate step prevents a deployment from overwriting an existing configuration:

```bash
if [ ! -e /usr/lib/cgi-bin/sprinkler.config ]; then
    sudo install -m 0660 -o www-data -g www-data \
        sprinkler.config.example /usr/lib/cgi-bin/sprinkler.config
fi
sudoedit /usr/lib/cgi-bin/sprinkler.config
```

GPIO numbers use Broadcom (BCM) numbering. Set the station pins for your relay board, then add the Pirate Weather API key, latitude, and longitude if weather reporting is desired.

### Install the systemd service

Install and start the scheduler service:

```bash
sudo install -m 0644 systemd/open-sprinkler.service /etc/systemd/system/open-sprinkler.service
sudo systemctl daemon-reload
sudo systemctl enable --now open-sprinkler.service
```

Check its status and recent logs:

```bash
systemctl status open-sprinkler.service
journalctl -u open-sprinkler.service -n 50 --no-pager
```

The service runs as `www-data` with `gpio` as a supplementary group, restarts after failures, and turns all configured relays off during a normal stop. It binds its control socket to `127.0.0.1:5555`, so relay commands are not accepted from other network hosts.

If this Pi previously used the legacy startup instructions, remove the `pigpiod &` and `sprinkler.py &` lines from `/etc/rc.local`. Also disable an existing `pigpiod` systemd service before enabling `open-sprinkler.service`. Only one scheduler process should control the relay pins.

### Give it a try
Open a web browser and enter the IP address of the Raspberry Pi. You should see the `index.py` page.
![pi-sprinker-timer main web page](/images/home.png)

### Test before connecting valves

Run the software tests from the repository checkout:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

With the valve power disconnected, use **Manual Control** to activate each station and confirm the corresponding relay indicator switches on and off. Active-low boards should remain off while the service starts and stops.

### Enable reboot and shutdown from the web page
Add the "www-data" user to the /etc/sudoers file by using visudo. NOTE: This weakens the security of your system in that a knowledgeable person might be able to reboot or shutdown your RPi. You have been warned.

`sudo visudo`

Add these lines to the bottom of the file.

```
www-data ALL=/sbin/shutdown
www-data ALL=NOPASSWD:/sbin/shutdown
```

### *Issues* :shit:
Need to make it look prettier.
