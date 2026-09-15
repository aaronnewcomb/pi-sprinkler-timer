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
sudo apt install lighttpd python3 python3-gpiozero python3-lgpio
```

GPIO access is performed only by the scheduler service. The CGI scripts send commands to that service over a loopback-only TCP socket.

## Installation
### Configure Lighttpd to run python scripts with password protection.

#### 1. Add the following to your /etc/lighttpd/lighttpd.conf configuration file:

```
auth.debug = 2
auth.backend = "plain"
auth.backend.plain.userfile = "/etc/.lighttpdpassword"
auth.require = ( "/cgi-bin/" =>
(
"method" => "basic",
"realm" => "Password protected area",
"require" => "user=admin"
)
)
$HTTP["url"] =~ "^/" {
    cgi.assign = (".py" => "/usr/bin/python3")
}
```

Change the username from "admin" to whatever you want.

#### 2. Create a file called /etc/.lighttpdpassword with one line in it:

`admin:password`

Change the password to whatever you want.

#### 3. Enable CGI for lighttpd

Run the following command to enable the cgi mod.

`lighty-enable-mod cgi`

#### 4. (optional) Add redirection to index.py

Create a file in your www root directory (i.e. /var/www/html) called index.html that will redirect traffic to the index.py script.

```
<html>
<head>
    <meta http-equiv="refresh" content="0; url=/cgi-bin/index.py" />
</head>
</html>
```

#### 5. Restart lighttpd

`sudo systemctl restart lighttpd`

### Copy the application

Clone the repository, then install the web files. The commands below use the paths expected by the included service:

```bash
sudo install -d -o www-data -g www-data /var/www/html/cgi-bin
sudo install -m 0755 -o www-data -g www-data ./*.py /var/www/html/cgi-bin/
sudo install -m 0644 -o www-data -g www-data index.html /var/www/html/index.html
```

Create the runtime configuration. This separate step prevents a deployment from overwriting an existing configuration:

```bash
if [ ! -e /var/www/html/cgi-bin/sprinkler.config ]; then
    sudo install -m 0660 -o www-data -g www-data \
        sprinkler.config.example /var/www/html/cgi-bin/sprinkler.config
fi
sudoedit /var/www/html/cgi-bin/sprinkler.config
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
