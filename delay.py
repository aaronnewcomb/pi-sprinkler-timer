#!/usr/bin/python

import cgi
import cgitb; cgitb.enable()  # for troubleshooting
import socket
import time
import datetime

# Create instance of FieldStorage
form = cgi.FieldStorage()
error = False

if form.getfirst("submit") == "Start":
    duration = form.getvalue('duration')
    if duration:
        clientsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        clientsocket.connect(('localhost', 5555))
        clientsocket.send("delay:%s" % duration)
        clientsocket.close()
    else: # If start was pressed but didn't specify a time
        error = True
elif form.getfirst("submit") == "Pause":
    clientsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    clientsocket.connect(('localhost', 5555))
    clientsocket.send("pause:0")
    clientsocket.close()
elif form.getfirst("submit") == "Resume":
    clientsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    clientsocket.connect(('localhost', 5555))
    clientsocket.send("resume:0")
    clientsocket.close()

time.sleep(1)
clientsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
clientsocket.connect(('localhost', 5555))
clientsocket.send("status:0")
while True:
    data = clientsocket.recv(64)
    if "disabled" in data:
        (data,futuretime) = data.split(":")
        localtime = time.asctime( time.localtime(float(futuretime)) )
    break
clientsocket.close()

print "Content-type: text/html\n\n"
print """
<html>
<head>
<title>Pi Sprinkler - Delay</title>
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
""" % data
if 'localtime' in globals():
    if float(futuretime) > time.time():
        print """<p style="color:red;font-weight: bold">Delay will expire at %s.<p>""" % localtime
if error:
    print """<p style="color:red;font-weight: bold">Duration must not be blank!<p>"""

print """
<h3>Set Rain Delay</h3>
<form action="/cgi-bin/delay.py" method="get">
<p>Duration (hours):<input type="text" name="duration" value="72" size="4"><input type="submit" name="submit" value="Start"></p>
<h3>Indefinite Hold</h3>
<input type="submit" name="submit" value="Pause"><input type="submit" name="submit" value="Resume">
</form>
</body>
</html>
"""
