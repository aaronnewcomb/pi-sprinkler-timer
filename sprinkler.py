#!/usr/bin/python

import pigpio
#from datetime import datetime
import time
import os
import SocketServer
import threading
import ConfigParser

### TBD
# Automatic delay when precipitation is reported by forecastio

### Global variables
running = False
enabled = True
delay = False
test = False
test_time = 0
pi = pigpio.pi()
futuretime = time.time()
lastrun = "never"
config = ConfigParser.ConfigParser()
# Full path of config file
config_file = "/var/www/html/cgi-bin/sprinkler.config"
config.read(config_file)
# Read in global station and program names
station = config.get("Station GPIOs","pins").split(",")
station = map(int,station)
program = config.get("Programs","names").split(",")

# Create some custom threading classes here
class ThreadedServer(SocketServer.BaseRequestHandler):
    def handle(self):
        #self.request.timeout(5)
        global running
        global enabled
        global delay
        global futuretime
        global lastrun
        global test
        global test_time
        data = "dummy"
        print "Client connected with ", self.client_address
        while len(data):
            data = self.request.recv(1024)
            if data:
                print "received " + data + " from client"
                # Set the response based on the data
                (command,var) = data.split(":")
                if "test_run" in command:
                    if var == "cancel":
                        running = False
                    else:
                        running = True
                        test = True
                        test_time = int(var)
                elif "status" in data:
                    if enabled == False:
                        # send the message to the client
                        self.request.send("disabled:%s" % str(futuretime))
                    elif running:
                        self.request.send("Running")
                    else:
                        self.request.send("Stopped. Last run %s" % (lastrun))
                elif "pause" in data:
                    enabled = False
                elif "resume" in data:
                    enabled = True
                    delay = False
                elif "delay" in data:
                    futuretime = time.time() + (int(var) * 3600)
                    delay = True
                elif "config_updated" in data:
                    config.read(config_file)
                else:
                    self.request.send("error")

        print "Client exited"
        self.request.close()

class ThreadedTCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
    timeout = 5

# Setup GPIO pins
for i in station:
    pi.set_mode(i, pigpio.OUTPUT)

def all_off():
    for i in station:
        pi.write(i, 1)

# Called from manual.py through socket
def test_run(t):
    global running
    for i in station:
        if running == True:
            pi.write(i, 0)
            now = time.time()
            while time.time() < now + t:
                server.handle_request()
                if running == False:
                    break
            pi.write(i, 1)
            time.sleep(.25)
    all_off()
    running = False

def run_program(prog):
    global running
    global lastrun
    lastrun = time.ctime()
    cfgfile = open(config_file,'w')
    config.set(prog, "lastrun", int(time.time()))
    config.write(cfgfile)
    cfgfile.close()
    config.read(config_file)
    for i in xrange(0, len(station)):
        if running == True:
            pi.write(station[i], 0)
            now = time.time()
            while time.time() < now + (int(config.get(prog, "sta_%s_dur" % (i+1)))* 60):
                server.handle_request()
                if running == False:
                    break
            pi.write(station[i], 1)
            time.sleep(.25)
    all_off()
    running = False
    print("Program finished.")

all_off()
print('Press Ctrl+{0} to exit'.format('Break' if os.name == 'nt' else 'C'))
server = ThreadedTCPServer(('',5555), ThreadedServer)

while True:
    server.handle_request()
    print ("request timeout")
    if test == True:
        test_run(test_time)
    if enabled == True and delay == False:
        for i in program:
            if config.has_option(i,"enable") and config.get(i,"enable") == "yes" and time.strftime("%H:%M") == config.get(i,"start"):
                # if it hasent run in [freq] days
                if time.time() > int(config.get(i, "lastrun")) + (int(config.get(i, "freq")) * 86400):
                    print("Program starting.")
                    running = True
                    run_program(i)
                else:
                    print("Now = %s\nLastrun = %s\nFrequency = %s") % (time.time(),int(config.get(i, "lastrun")),(int(config.get(i, "freq")) * 86400))
                    print("Program already run. Skipping program.")

    if time.time() >= futuretime and delay == True:
        delay = False

all_off()
client.close()
