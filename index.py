#!/usr/bin/python

import cgi
import cgitb; cgitb.enable()  # for troubleshooting
import ConfigParser
import datetime
import urllib2
import optparse
import json
import socket

config = ConfigParser.ConfigParser()
today = datetime.datetime.today()
yesterday = today - datetime.timedelta(days=1)
url = "https://api.forecast.io/forecast/"

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

if not config.read("/var/www/html/cgi-bin/sprinkler.config"):
    # lets create that config file for next time...
    try:
        cfgfile = open("/var/www/html/cgi-bin/sprinkler.config",'w')

        # add the settings to the structure of the file, and lets write it out...
        config.add_section('forcastio')
        config.set('forcastio','apikey','key')
        config.set('forcastio','lat','37.774929y')
        config.set('forcastio','lng','-122.419416')
        config.write(cfgfile)
        cfgfile.close()
        print ("""New config file successfully created! Be sure to edit the settings and add your <a href="https://darksky.net/dev/">forecastio api key</a>.""")
    except:
        print ("Config file could not be created for first run.")

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
