#!/usr/bin/python

import pigpio
from datetime import datetime
import time
import os
from apscheduler.schedulers.background import BackgroundScheduler
import SocketServer
import threading

### TBD
# Start a thread to update variables when notified by settings.py
# Automatic delay when precipitation is reported by forecastio

### Global variables
# Change this to match the GPIO numbers for the pins you connect to your relay board
station = [5,6,12,13,16,19,20,21]

running = False
enabled = True
delay = False
pi = pigpio.pi()
futuretime = time.time()

# Create some custom threading classes here
class ThreadedServer(SocketServer.BaseRequestHandler):
    def handle(self):
        global running
        global enabled
        global delay
        global futuretime
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
                elif "status" in data:
                    if enabled == False:
                        # send the message to the client
                        self.request.send("disabled:%s" % str(futuretime))
                    elif running:
                        self.request.send("running")
                    else:
                        self.request.send("stopped")
                elif "pause" in data:
                    scheduler.pause()  # What about delay then pause?
                    enabled = False
                    delay = False
                    futuretime = time.time()
                elif "resume" in data:
                    scheduler.resume()
                    enabled = True
                    delay = False
                elif "delay" in data:
                    scheduler.pause()
                    futuretime = time.time() + (float(var) * 3600)
                    enabled = False
                    delay = True
                else:
                    self.request.send("error")

        print "Client exited"
        self.request.close()

        if "test_run" in command:
            if not var == "cancel":
                temp(var)
                #test_run(var)
class ThreadedTCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
    pass

class ThreadingTimer(object):
    def __init__(self, interval=30):
        self.interval = interval
        thread = threading.Thread(target=self.run, args=())
        thread.daemon = True                            # Daemonize thread
        thread.start()                                  # Start the execution

    def run(self):
        """ Method that runs forever """
        global running
        global enabled
        global delay
        global futuretime
        while True:
            # Do something
            if time.time() >= futuretime and enabled == False and delay == True:
                scheduler.resume()
                enabled = True
                delay = False
            time.sleep(self.interval)

# Setup GPIO pins
for i in station:
    pi.set_mode(i, pigpio.OUTPUT)

def all_off():
    for i in station:
        pi.write(i, 1)

def temp(t):
    global running
    x = 1
    while running:
        print "Station %s ON" % x
        time.sleep(int(t))
        print "Station %s OFF" % x
        time.sleep(1)
        x+=1
        if x > len(station):
            running = False
    all_off()
    print "JOB ENDED"

def test_run(t):
    running = True
    for i in station:
        pi.write(station[i], 0)
        time.sleep(t)
        pi.write(station[i], 1)
        time.sleep(1)
    for i in station:
        pi.write(station[i], 1)
    running = False

# For now, this function is your main program. This will be implemented in program.py later.
def job1():
    print("Job 1 running!")
    running = True
    pi.write(station[0], 0)
    time.sleep(600)
    pi.write(station[0], 1)
    time.sleep(1)
    pi.write(station[1], 0)
    time.sleep(600)
    pi.write(station[1], 1)
    time.sleep(1)
    pi.write(station[0], 0)
    time.sleep(300)
    pi.write(station[0], 1)
    time.sleep(1)
    pi.write(station[1], 0)
    time.sleep(300)
    pi.write(station[1], 1)
    time.sleep(1)
    pi.write(station[2], 0)
    time.sleep(600)
    pi.write(station[2], 1)
    time.sleep(1)
    pi.write(station[3], 0)
    time.sleep(600)
    pi.write(station[3], 1)
    time.sleep(1)
    pi.write(station[4], 0)
    time.sleep(600)
    pi.write(station[4], 1)
    time.sleep(1)
    pi.write(station[5], 0)
    time.sleep(600)
    pi.write(station[5], 1)
    time.sleep(1)
    pi.write(station[6], 0)
    time.sleep(600)
    pi.write(station[6], 1)
    running = False

if __name__ == '__main__':
    # Maker sure that all stations are turned off initially
    all_off()

    scheduler = BackgroundScheduler()
    # Change this to manage what days and time you want to run your job
    scheduler.add_job(job1, 'cron', day_of_week='mon,wed,fri,sun', hour=6, minute=30)
    scheduler.start()
    print('Press Ctrl+{0} to exit'.format('Break' if os.name == 'nt' else 'C'))

    server = ThreadedTCPServer(('',5555), ThreadedServer)
    server.serve_forever()
    timer = ThreadedTimer()

all_off()
client.close()
scheduler.shutdown(wait=False)
