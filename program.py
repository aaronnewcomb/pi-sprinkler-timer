#!/usr/bin/python

import cgi
import cgitb; cgitb.enable()  # for troubleshooting
import socket
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

clientsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

def notify():
    # Let the daemon know to rescan the config file
    clientsocket.connect(('localhost', 5555))
    clientsocket.send('config_updated:0')
    clientsocket.close()

def update_config(prog):
    cfgfile = open(config_file,'w')
    # add the settings to the structure of the file, and lets write it out...
    if form.getfirst("enabled") == "yes":
        config.set(prog,'enable','yes')
    else:
        config.set(prog,'enable','no')
    config.set(prog,'start',form.getfirst("start_time"))
    config.set(prog,'freq',form.getfirst("freq"))
    config.set(prog,'sta_1_dur',form.getfirst("sta_1_dur"))
    config.set(prog,'sta_2_dur',form.getfirst("sta_2_dur"))
    config.set(prog,'sta_3_dur',form.getfirst("sta_3_dur"))
    config.set(prog,'sta_4_dur',form.getfirst("sta_4_dur"))
    config.set(prog,'sta_5_dur',form.getfirst("sta_5_dur"))
    config.set(prog,'sta_6_dur',form.getfirst("sta_6_dur"))
    config.set(prog,'sta_7_dur',form.getfirst("sta_7_dur"))
    config.set(prog,'sta_8_dur',form.getfirst("sta_8_dur"))
    config.write(cfgfile)
    cfgfile.close()
    notify()

if form.getfirst("submit"):
    # Update the settings file
    update_config(form.getfirst("program_number"))

### TODO: Read in existing values and populate if exist

print "Content-type: text/html\n\n"
print """
<html>
<head>
<title>Pi Sprinkler - Program Editor</title>
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
<h2>Program Editor</h2>
"""
for x in xrange(0, len(program)):
    print """
    <h3 style="text-decoration: underline">Program Number %s</h3>
    <form action="/cgi-bin/program.py" method="get">
    """ % (x+1)
    if config.has_option(program[x],"enable") and config.get(program[x],"enable") == "yes":
        print """<p style="font-weight: bold">Enable: <input type="checkbox" name="enabled" value="yes" checked>"""
    else:
        print """<p style="font-weight: bold">Enable: <input type="checkbox" name="enabled" value="yes">"""
    if config.has_option(program[x],"start"):
        print """<p style="font-weight: bold">Start Time: <input type="time" name="start_time" value="%s">""" % (config.get(program[x],"start"))
    else:
        print """<p style="font-weight: bold">Start Time: <input type="time" name="start_time">"""
    print """<p style="font-weight: bold">Frequncy:<br>"""
    if config.has_option(program[x],"freq") and config.get(program[x],"freq") == "1":
        print """<input type="radio" name="freq" value="1" checked>Every 1 Day<br>"""
    else:
        print"""<input type="radio" name="freq" value="1">Every 1 Day<br>"""
    if config.has_option(program[x],"freq") and config.get(program[x],"freq") == "2":
        print """<input type="radio" name="freq" value="2" checked>Every 2 Day<br>"""
    else:
        print"""<input type="radio" name="freq" value="2">Every 2 Day<br>"""
    if config.has_option(program[x],"freq") and config.get(program[x],"freq") == "3":
        print """<input type="radio" name="freq" value="3" checked>Every 3 Day<br>"""
    else:
        print"""<input type="radio" name="freq" value="3">Every 3 Day<br>"""

    for y in xrange(0, len(station)):
        if config.has_option(program[x],"sta_%s_dur" % (y+1)):
            print """<p style="font-weight: bold">Station %s Duration (minutes): <input type="text" name="sta_%s_dur" value="%s" size="3"></p>""" % (y+1, y+1,config.get(program[x],"sta_%s_dur" % (y+1)))
        else:
            print """<p style="font-weight: bold">Station %s Duration (minutes): <input type="text" name="sta_%s_dur" value="0" size="3"></p>""" % (y+1, y+1)
    print """
    <input type="hidden" name="program_number" value="program%s">
    <input type=submit name="submit" value="Update Program %s"></form><hr>
    """ % (x+1, x+1)

print """
</body>
</html>
"""
