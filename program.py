#!/usr/bin/python

import cgi
import cgitb; cgitb.enable()  # for troubleshooting

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
<h3>Work In Progress</h3>
This page is under construction. In the meantime, edit your program directly in scheduler.py.
</body>
</html>
"""
