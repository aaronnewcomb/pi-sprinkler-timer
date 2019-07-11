# pi-sprinkler-timer
A DIY web driven scheduler system for the Raspberry Pi written in Python using lighttpd and pigpio. This is typically used to support a irrigation system with multiple sprinkler valves, but you could also use it to control other devices.

(If you are looking for a more turnkey and feature rich solution for your RPi, I highly recommend [OpenSprinkler Pi](https://opensprinkler.com/product/opensprinkler-pi/) instead.)

## Parts:
* Raspberry Pi (or other dev board capable of running Python and Lighttpd)
 * WiFi dongle (if not using RPi v3)
 * Power Supply for RPi
* 24V AC Sprinkler Power Supply
* Sprinkler Valves
* 5V Relay Board

## Pre-requisites:
* Lighttpd must be installed
* [Pigpio](http://abyz.co.uk/rpi/pigpio/) must be installed (Installed by default on Raspbian)
* RPi must be configured to connect to your network

## Installation:
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
    cgi.assign = (".py" => "/usr/bin/python")
}
```

Change the username from "admin" to whatever you want.

#### 2. Create a file called /etc/.lighttpdpassword with one line in it:

`admin:password`

Change the password to whatever you want.

#### 3. Enable cgi for Lighttpd

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

#### 5. Restart Lighttpd.

`sudo service lighttpd restart`

### Copy scripts
#### 1. Download this github repository and copy index.html to your web root directory.
#### 2. Copy all the other ".py" scripts to your cgi-bin directory.
#### 3. Give files in your cgi-bin location execute privilages and the correct ownership.

```
sudo chmod +x /path-to-your-cgi-bin-directory/*
sudo chown www-data:www-data /path-to-your-cgi-bin-directory/*
```

#### 4. Add pigpiod and the scheduler to rc.local so they start when the Pi boots up.

`sudo nano /etc/rc.local`

Add ...

```
pigpiod &
/<path-to-your-cgi-bin-directory>/sprinkler.py &
```

... before the "exit" statement. Reboot your Raspberry Pi.

### Give it a try
Reboot your RPi. Open a web browser and type in the IP address of your RPi. You should see the index.py page.
![pi-sprinker-timer main web page](/images/home.png)

### Add your GPIO pins
The first time you connect to the web page a new config file should be created. Open the sprinkler.config file and change the values in [Station GPIOs] to match the GPIO pins you connected to your relay board.

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
