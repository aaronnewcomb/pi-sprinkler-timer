# pi-sprinkler-timer
A web driven scheduler system for the Raspberry Pi written in Python using lighttpd and pigpio.

Parts:
Raspberry Pi (or other dev board capable of running Python and Lighttpd)
WiFi dongle (if not using RPi v3)
Power Supply for RPi
24V AC Sprinkler Power Supply
Sprinler Valves
5V Relay Board

Pre-requisites:
Lighttpd must be installed
Pigpio must be installed and configured to start automatically
RPi must be configured to connect to your network

Installation:
1. Configure Lighttpd to run python scripts with password protection.

Add the following to your /etc/lighttpd/lighttpd.conf configuration file:

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

Change the username from "admin" to whatever you want.

Create a file called /etc/.lighttpdpassword with one line in it:

admin:password

Change the password to whatever you want.

2. Install pigpio



