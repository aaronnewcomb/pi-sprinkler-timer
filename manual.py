#!/usr/bin/python3

import socket
import time
import configparser

from cgi_utils import QueryForm
from app_paths import CONFIG_FILE

# Create instance of FieldStorage
form = QueryForm()
error = False
config = configparser.ConfigParser()
config_file = CONFIG_FILE
config.read(config_file)
# Read in global station and program names
station = config.get("Station GPIOs","pins").split(",")
station = list(map(int,station))
program = config.get("Programs","names").split(",")


def scheduler_command(command, response_size=64):
    clientsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        clientsocket.connect(('localhost', 5555))
        clientsocket.sendall(command.encode("utf-8"))
        if response_size:
            return clientsocket.recv(response_size).decode("utf-8")
    finally:
        clientsocket.close()

if form.getfirst("test") == "Start":
    duration = form.getvalue('duration')
    if duration:
        scheduler_command("test_run:%s" % duration, response_size=0)
    else:
        error = True
elif form.getfirst("test") == "Cancel":
    scheduler_command("test_run:cancel", response_size=0)

time.sleep(.25)
data = scheduler_command("status:0")
if data == "Running":
    running = True
elif "Delayed" in data:
    (data,futuretime) = data.split(":")
    localtime = time.asctime(time.localtime(float(futuretime)))
    data = "Delayed until %s" % localtime
    running = False
else:
    running = False

if form.getfirst("test") != "Start" and running == False:
    for pin in station:
        requested_state = form.getfirst(str(pin))
        if requested_state == "ON":
            scheduler_command("station_on:%s" % pin)
        elif requested_state == "OFF":
            scheduler_command("station_off:%s" % pin)

status_response = scheduler_command("station_status:0", response_size=1024)
station_states = dict(item.split("=", 1) for item in status_response.split(","))
status = {
    pin: "green" if station_states.get(str(pin)) == "on" else ""
    for pin in station
}

print("Content-type: text/html\n\n")
print("""
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
""" % data)

for x in range(0, len(station)):
    print("""<p style="color:%s;font-weight: bold">Station %s: <input type="submit" name="%s" value="ON" style="background-color:%s;"><input type="submit" name="%s" value="OFF"></p>""" % (status[station[x]],x+1,station[x],status[station[x]],station[x]))

#print form.getfirst("5","bonk")
#cgi.print_form(form)

print("""<h3>Test Run</h3>""")
if running:
    print("""<p style="color:green;font-weight: bold">Duration (seconds): RUNNING <input type="submit" name="test" value="Cancel"></p>""")
else:
    print("""<p>Duration (seconds):<input type="text" name="duration" value="10" size="4"><input type="submit" name="test" value="Start"><input type="submit" name="test" value="Cancel"></p>""")
    if error:
        print("""<p style="color:red;font-weight: bold">Duration must not be blank!<p>""")

print("""
</form>
<h3>System Control</h3>
<form action="/cgi-bin/reboot.py" method="get">
<input type="submit" name="reboot" value="Reboot"><input type="submit" name="reboot" value="Shutdown">
</form>
</body>
</html>
""")
