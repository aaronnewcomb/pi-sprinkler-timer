#!/usr/bin/python3

import configparser
import datetime
import time
import urllib.error
import urllib.request
import optparse
import json
import socket

config = configparser.ConfigParser()
today = datetime.datetime.today()
yesterday = today - datetime.timedelta(days=1)
url = "https://api.pirateweather.net/forecast/"
# Full path of config file
config_file = "/var/www/html/cgi-bin/sprinkler.config"
config_lines = """# Change this to match the GPIO numbers for the pins you connect to your relay board
[Station GPIOs]
pins = 5,6,12,13,16,19,20,21

[Programs]
names = program1,program2,program3,program4

[OpenWeatherMap]
apikey =
zipcode =

[forecastio]
apikey =
lat =
lng =

[program1]
lastrun = 0

[program2]
lastrun = 0

[program3]
lastrun = 0

[program4]
lastrun = 0"""

clientsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
clientsocket.connect(('localhost', 5555))
clientsocket.sendall("status:0".encode("utf-8"))
while True:
    data = clientsocket.recv(64).decode('utf-8')
    if "Delayed" in data:
        (data,futuretime) = data.split(":")
        localtime = time.asctime( time.localtime(float(futuretime)) )
        data = "Delayed until %s" % (localtime)
    break
clientsocket.close()

print ("Content-type: text/html\n\n")
print ("""
<html>
<head>
<title>Pi Sprinkler - Home</title>
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
<p>Current status: %s</p>
<p>
""" % data)

if not config.read(config_file):
    # lets create that config file for next time...
    try:
        f = open(config_file,"w")
    except AssertionError as error:
        print(error)
        print ("Config file could not be opened.")
    else:
        f.writelines(config_lines.splitlines(True))
        f.close()
        print ("""New config file successfully created! Be sure to <a href="http://192.168.0.159:8000/cgi-bin/settings.py">edit the settings</a> and add your <a href="https://darksky.net/dev/">forecastio api key</a>.""")
        config.read(config_file)

api = config.get("forecastio","apikey")
lat = config.get("forecastio","lat")
lng = config.get("forecastio","lng")

def get_precip(i):
    precip = i["precipIntensityMax"]
    if precip <= .002:
        return "None"
    elif precip <= .017:
        return "Very Light"
    elif precip <= .1:
        return "Light"
    elif precip <= .4:
        return "Moderate"
    elif precip > .4:
        return "Heavy"

print ("<h3>Weather Report</h3>")
print ("Current Time: %s<br>" % today)
if api and lat and lng:
    try:
        req = urllib.request.Request(url+api+"/"+("%s,%s" % (lat,lng)))
        response = urllib.request.urlopen(req, timeout=10)
        req_y = urllib.request.Request(url+api+"/"+("%s,%s,%s" % (lat,lng,yesterday.replace(microsecond=0).isoformat())))
        response_y = urllib.request.urlopen(req_y, timeout=10)
        parsed = json.loads(response.read().decode('utf-8'))
        parsed_y = json.loads(response_y.read().decode('utf-8'))
        current = parsed["currently"]
        daily = parsed["daily"]["data"][0]
        daily_y = parsed_y["daily"]["data"][0]
    except (urllib.error.URLError, ValueError, KeyError, IndexError):
        print ("Weather data is temporarily unavailable.<br>")
    else:
        print ("Current Conditions: %s<br>" % current["summary"])
        print ("Current Temperature: %s<br>" % current["temperature"])
        print ("Today's Forecasted High Temperature: %s<br>" % daily["temperatureMax"])
        print ("Yesterday's High Temperature: %s<br>" % daily_y["temperatureMax"])
        print ("Current Precipitation: %s<br>" % get_precip(daily))
        print ("Yesterday's Precipitation: %s<br>" % get_precip(daily_y))
else:
    print ("Weather is not configured. Add a Pirate Weather API key, latitude, and longitude in Settings.<br>")

print ("""
</p></body>
</html>
""")
