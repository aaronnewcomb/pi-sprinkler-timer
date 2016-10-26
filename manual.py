#!/usr/bin/python

import pigpio
import cgi
import cgitb; cgitb.enable()  # for troubleshooting
import socket
import time

# Create instance of FieldStorage
form = cgi.FieldStorage()
error = False

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

time.sleep(1)
clientsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
clientsocket.connect(('localhost', 5555))
clientsocket.send("status:0")
while True:
    data = clientsocket.recv(64)
    if data == "running":
        running = True
        break
    else:
        running = False
        break
    if not data:
        break
clientsocket.close()

pi = pigpio.pi()
station = [5,6,12,13,16,19,20,21]
status = {}

for i in station:
    pi.set_mode(i, pigpio.OUTPUT)
    pi.write(i, 1)

for i in station:
    if form.getfirst(str(i),"OFF") == "ON":
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
    print """<p style="color:%s;font-weight: bold">Station %s: <input type="submit" name="%s" value="ON"><input type="submit" name="%s" value="OFF"></p>""" % (status[station[x]],x+1,station[x],station[x])

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
