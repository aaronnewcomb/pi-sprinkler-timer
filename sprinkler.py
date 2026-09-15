#!/usr/bin/python3

import configparser
import os
import signal
import socketserver
import time

from gpio_backend import RelayBank

### TBD
# Automatic delay when precipitation is reported by forecastio

### Global variables
running = False
enabled = True
delay = False
test = False
test_time = 0
futuretime = time.time()
lastrun = "never"
shutdown_requested = False
config = configparser.ConfigParser()
# Full path of config file
config_file = "/var/www/html/cgi-bin/sprinkler.config"
config.read(config_file)
# Read in global station and program names
station = config.get("Station GPIOs","pins").split(",")
station = list(map(int,station))
program = config.get("Programs","names").split(",")
relays = RelayBank(station)

# Create some custom threading classes here
class ThreadedServer(socketserver.BaseRequestHandler):
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
        print("Client connected with ", self.client_address)
        while len(data):
            raw_data = self.request.recv(1024)
            if raw_data:
                data = raw_data.decode("utf-8")
                print("received " + data + " from client")
                # Set the response based on the data
                (command,var) = data.split(":", 1)
                if command == "test_run":
                    if var == "cancel":
                        running = False
                    else:
                        running = True
                        test = True
                        test_time = int(var)
                elif command == "status":
                    if enabled == False:
                        # send the message to the client
                        self.request.sendall(("Disabled. Last run %s" % (lastrun)).encode("utf-8"))
                    elif running:
                        self.request.sendall("Running".encode("utf-8"))
                    elif delay:
                        self.request.sendall(("Delayed:%s" % str(futuretime)).encode("utf-8"))
                    else:
                        self.request.sendall(("Stopped. Last run %s" % (lastrun)).encode("utf-8"))
                elif command == "station_status":
                    states = [
                        "%s=%s" % (pin, "on" if relays.is_on(pin) else "off")
                        for pin in station
                    ]
                    self.request.sendall(",".join(states).encode("utf-8"))
                elif command == "station_on":
                    pin = int(var)
                    if pin not in station or running:
                        self.request.sendall("error".encode("utf-8"))
                    else:
                        relays.all_off()
                        relays.on(pin)
                        self.request.sendall("ok".encode("utf-8"))
                elif command == "station_off":
                    pin = int(var)
                    if pin not in station or running:
                        self.request.sendall("error".encode("utf-8"))
                    else:
                        relays.off(pin)
                        self.request.sendall("ok".encode("utf-8"))
                elif command == "pause":
                    enabled = False
                elif command == "resume":
                    enabled = True
                    delay = False
                elif command == "delay":
                    futuretime = time.time() + (int(var) * 3600)
                    delay = True
                elif command == "config_updated":
                    config.read(config_file)
                else:
                    self.request.sendall("error".encode("utf-8"))
            else:
                data = ""

        print("Client exited")
        self.request.close()

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    timeout = 5

def all_off():
    relays.all_off()

# Called from manual.py through socket
def test_run(t):
    global running
    for i in station:
        if running == True:
            relays.on(i)
            now = time.time()
            while time.time() < now + t:
                server.handle_request()
                if running == False:
                    break
            relays.off(i)
            time.sleep(.25)
    all_off()
    running = False

def run_program(prog):
    global running
    global lastrun
    lastrun = time.ctime()
    cfgfile = open(config_file,'w')
    config.set(prog, "lastrun", str(int(time.time())))
    config.write(cfgfile)
    cfgfile.close()
    config.read(config_file)
    for i in range(0, len(station)):
        if running == True:
            relays.on(station[i])
            now = time.time()
            while time.time() < now + (int(config.get(prog, "sta_%s_dur" % (i+1)))* 60):
                server.handle_request()
                if running == False:
                    break
            relays.off(station[i])
            time.sleep(.25)
    all_off()
    running = False
    print("Program finished.")

def request_shutdown(_signum, _frame):
    global shutdown_requested
    global running
    shutdown_requested = True
    running = False


all_off()
signal.signal(signal.SIGTERM, request_shutdown)
signal.signal(signal.SIGINT, request_shutdown)
print('Press Ctrl+{0} to exit'.format('Break' if os.name == 'nt' else 'C'))
server = ThreadedTCPServer(('127.0.0.1', 5555), ThreadedServer)

try:
    while not shutdown_requested:
        server.handle_request()
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
                        print("Now = %s\nLastrun = %s\nFrequency = %s" % (time.time(),int(config.get(i, "lastrun")),(int(config.get(i, "freq")) * 86400)))
                        print("Program already run. Skipping program.")

        if time.time() >= futuretime and delay == True:
            delay = False
finally:
    all_off()
    server.server_close()
    relays.close()
