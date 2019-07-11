#!/usr/bin/python

import cgi
import cgitb; cgitb.enable()  # for troubleshooting
import ConfigParser
import datetime
import time
import urllib2
import optparse
import json
import socket

config = ConfigParser.ConfigParser()
today = datetime.datetime.today()
yesterday = today - datetime.timedelta(days=1)
url = "https://api.forecast.io/forecast/"
# Full path of config file
config_file = "/var/www/html/cgi-bin/sprinkler.config"
config_lines = """# Change this to match the GPIO numbers for the pins you connect to your relay board
[Station GPIOs]
pins = 5,6,12,13,16,19,20,21

[Programs]
names = program1,program2,program3,program4

[OpenWeatherMap]
apikey = 4d741c61036a070a425c19446dc92392
zipcode = 94510

[forecastio]
apikey = 8f59e11beab60fee52912ab48354b0b9
lat = 38.049365
lng = -122.158578

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
clientsocket.send("status:0")
while True:
    data = clientsocket.recv(64)
    if "disabled" in data:
        (data,futuretime) = data.split(":")
        localtime = time.asctime( time.localtime(float(futuretime)) )
        data = "Disabled unitl %s" % (localtimed)
    break
clientsocket.close()

print "Content-type: text/html\n\n"
print """
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
""" % data

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
req = urllib2.Request(url+api+"/"+("%s,%s" % (lat,lng)))
response = urllib2.urlopen(req)
req_y = urllib2.Request(url+api+"/"+("%s,%s,%s" % (lat,lng,yesterday.replace(microsecond=0).isoformat())))
response_y = urllib2.urlopen(req_y)
parsed = json.loads(response.read())
parsed_y = json.loads(response_y.read())
current = parsed["currently"]
daily = parsed["daily"]["data"][0]
daily_y = parsed_y["daily"]["data"][0]

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

print "<h3>Weather Report</h3>"
print "Current Time: %s<br>" % today
print "Current Conditions: %s<br>" % current["summary"]
print "Current Temperature: %s<br>" % current["temperature"]
print "Today's Forecasted High Temperature: %s<br>" % daily["temperatureMax"]
print "Yesterday's High Temperature: %s<br>" % daily_y["temperatureMax"]
print "Current Precipitation: %s<br>" % get_precip(daily)
print "Yesterday's Precipitation: %s<br>" % get_precip(daily_y)

print """
</p></body>
</html>
"""
