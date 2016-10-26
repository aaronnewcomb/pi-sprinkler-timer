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
now = datetime.datetime.now()

def notify():
    clientsocket.connect(('localhost', 5555))
    clientsocket.send('config_updated')
    clientsocket.close()

def create_default():
    try:
        cfgfile = open(config_file,'w')

        # add the settings to the structure of the file, and lets write it out...
        config.add_section('forcastio')
        config.set('forcastio','apikey','key')
        config.set('forcastio','lat','37.774929')
        config.set('forcastio','lng','-122.419416')
        config.write(cfgfile)
        cfgfile.close()
        print ("New config file successfully created!")
        notify()
    except:
        print ("Config file could not be created.")

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
