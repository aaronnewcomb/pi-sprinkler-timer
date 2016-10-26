#!/usr/bin/python

import cgi
import cgitb; cgitb.enable()  # for troubleshooting
import os

# Create instance of FieldStorage
form = cgi.FieldStorage()
# Get data from fields
action = form.getvalue('reboot')

print "Content-type: text/html\n\n"
print """
<html>
<head>
<title>Pi Sprinkler - Reboot</title>
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
<tr><th><a href="/">Home</a></th><th><a href="/cgi-bin/program.py">Program</a></th><th><a href="/cgi-bin/delay.py">Delay?</a></th><th><a href="/cgi-bin/manual.py">Manual Control</a><th><a href="/cgi-bin/settings.py">Settings</a></th></tr>
</table>
</p>
<h3>Manual Control</h3>
<form action="/cgi-bin/reboot.py" method="get">
"""

if "Reboot" in action:
    print """
    Are you sure you want to reboot the system???<br>
    <input type="hidden" name="reboot" value="reboot_now">
    <input type="submit" value="Submit">
    """
elif "Shutdown" in action:
    print """
    Are you sure you want to shutdown the system???<br>
    <input type="hidden" name="reboot" value="shutdown_now">
    <input type="submit" value="Submit">
    """
elif "reboot_now" in action:
    print "Rebooting the system ..."
elif "shutdown_now" in action:
    print "Shutting down the system ..."

#print form.getfirst("5","bonk")
#cgi.print_form(form)

print """
</form>
</body>
</html>
"""
if "reboot_now" in action:
    os.system("sudo shutdown -r now")
elif "shutdown_now" in action:
    os.system("sudo shutdown -h now")
