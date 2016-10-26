# pi-sprinkler-timer
A web driven scheduler system for the Raspberry Pi written in Python using lighttpd and pigpio.

## Parts:
Raspberry Pi (or other dev board capable of running Python and Lighttpd)
WiFi dongle (if not using RPi v3)
Power Supply for RPi
24V AC Sprinkler Power Supply
Sprinler Valves
5V Relay Board

## Pre-requisites:
Lighttpd must be installed
[Pigpio](http://abyz.co.uk/rpi/pigpio/) must be installed and configured to start automatically
RPi must be configured to connect to your network

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

#### 3. Restart Lighttpd.
`sudo service lighttpd restart`

### Copy scripts
#### 1. Download this github repository and copy index.html to your web root directory.
#### 2. Copy all the other ".py" scripts to your cgi-bin directory.



