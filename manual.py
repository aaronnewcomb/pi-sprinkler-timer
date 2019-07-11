#!/usr/bin/python

import pigpio
import cgi
import cgitb; cgitb.enable()  # for troubleshooting
import socket
import time
import ConfigParser

# Create instance of FieldStorage
form = cgi.FieldStorage()
error = False
config = ConfigParser.ConfigParser()
config_file = "/var/www/html/cgi-bin/sprinkler.config"
config.read(config_file)
# Read in global station and program names
station = config.get("Station GPIOs","pins").split(",")
station = map(int,station)
program = config.get("Programs","names").split(",")
pi = pigpio.pi()

if form.getfirst("test") == "Start":
    duration = form.getvalue('duration')
    if duration:
        clientsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        clientsocket.connect(('localhost', 5555))
        clientsocket.send("test_run:%s" % duration)
        clientsocket.close()
    else:
        error = True
elif form.getfirst("test") == "Cancel":
    clientsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    clientsocket.connect(('localhost', 5555))
    clientsocket.send("test_run:cancel")
    clientsocket.close()

time.sleep(.25)
clientsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
clientsocket.connect(('localhost', 5555))
clientsocket.send("status:0")
while True:
    data = clientsocket.recv(64)
    if data == "Running":
        running = True
        break
    else:
        running = False
        break
    if not data:
        break
clientsocket.close()

status = {}

for i in station:
    pi.set_mode(i, pigpio.OUTPUT)
    if form.getfirst("test") != "Start" and running == False:
        if form.getfirst(str(i)) == "ON":
            pi.write(i, 0)
        else:
            pi.write(i, 1)

for i in station:
    if pi.read(i) == 0:
        status[i] = "green"
    else:
        status[i] = ""

print "Content-type: text/html\n\n"
print """
<html>
<head>
<title>Pi Sprinkler - Manual Control</title>
<style>
table, th, td {
    border: 1px solid black;
    border-collapse: collapse;
}
</style>
</head>
<body>
  <h3>Menu</h3>
<p>
<table style="">
<tr><th><a href="/">Home</a></th><th><a href="/cgi-bin/program.py">Program</a></th><th><a href="/cgi-bin/delay.py">Delay</a></th><th><a href="/cgi-bin/manual.py">Manual Control</a><th><a href="/cgi-bin/settings.py">Settings</a></th></tr>
</table>
</p>
<p>Current status: %s</p>
<h3>Manual Station Control</h3>
<form action="/cgi-bin/manual.py" method="get">
""" % data

for x in xrange(0, len(station)):
    print """<p style="color:%s;font-weight: bold">Station %s: <input type="submit" name="%s" value="ON" style="background-color:%s;"><input type="submit" name="%s" value="OFF"></p>""" % (status[station[x]],x+1,station[x],status[station[x]],station[x])

#print form.getfirst("5","bonk")
#cgi.print_form(form)

print """<h3>Test Run</h3>"""
if running:
    print """<p style="color:green;font-weight: bold">Duration (seconds): RUNNING <input type="submit" name="test" value="Cancel"></p>"""
else:
    print """<p>Duration (seconds):<input type="text" name="duration" value="10" size="4"><input type="submit" name="test" value="Start"><input type="submit" name="test" value="Cancel"></p>"""
    if error:
        print """<p style="color:red;font-weight: bold">Duration must not be blank!<p>"""

print """
</form>
<h3>System Control</h3>
<form action="/cgi-bin/reboot.py" method="get">
<input type="submit" name="reboot" value="Reboot"><input type="submit" name="reboot" value="Shutdown">
</form>
</body>
</html>
"""
