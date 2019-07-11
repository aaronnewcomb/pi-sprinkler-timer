#!/usr/bin/python

import cgi
import cgitb; cgitb.enable()  # for troubleshooting
import ConfigParser
import socket
import os
import datetime

config = ConfigParser.ConfigParser()
clientsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
form = cgi.FieldStorage()
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
lastrun = 0r

[program4]
lastrun = 0"""
now = datetime.datetime.now()

def notify():
    clientsocket.connect(('localhost', 5555))
    clientsocket.send('config_updated:0')
    clientsocket.close()

def create_default():
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

if not config.read(config_file):
    # lets create that config file for next time...
    create_default()

print "Content-type: text/html\n\n"
print """
<html>
<head>
<title>Pi Sprinkler - Settings</title>
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
"""

if form.getfirst("submit","") == "Change Settings":
    print """<h3>Change Settings</h3><div style="color:red">Warning: Chaning these settings could render the system useless!</div></p>"""
    for section_name in config.sections():
        print "<p><strong>Section: </strong>%s<br>" % section_name
        for name, value in config.items(section_name):
            print """%s = <input type="text" name="%s:%s" value="%s"><br>""" % (name, section_name,value,value)
    print """
    </p><p>
    <form action="/cgi-bin/settings.py" method="get">
    <input type="submit" name="submit" value="Update Settings"><input type="submit" name="submit" value="Default Settings"><input type="submit" name="submit" value="Cancel">
    </form>
    """
elif form.getfirst("submit","") == "Update Settings":
    print
elif form.getfirst("submit","") == "Default Settings":
    print """
    <h3>Revert To Default Settings</h3>
    <div style="color:red">Warning: Are you sure you want to change all the settings to the defaults?</div>
    </p>
    <form action="/cgi-bin/settings.py" method="get">
    <input type="submit" name="submit" value="OK"><input type="submit" name="submit" value="Cancel">
    </form>
    """
elif form.getfirst("submit","") == "OK":
    os.system ("cp %s %s.%s" % (config_file, config_file, now.isoformat()))
    os.system ("rm %s" % config_file)
    create_default()
    print """
    <h3>Revert To Default Settings</h3>
    <div style="color:red">Your settings have been reverted to the defaults.</div>
    </p>
    """
else:
    print "<h3>Current Settings</h3></p>"
    for section_name in config.sections():
        print "<p><strong>Section: </strong>%s<br>" % section_name
        for name, value in config.items(section_name):
            print " %s = %s<br>" % (name, value)
    print """
    </p><p>
    <form action="/cgi-bin/settings.py" method="get">
    <input type="submit" name="submit" value="Change Settings">
    </form>
    """

print """
</body>
</html>
"""
