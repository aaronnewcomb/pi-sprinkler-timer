# Garage door MQTT monitor

The optional garage-door service reads a reed switch and publishes its state to
an MQTT broker for Home Assistant or another home-automation system. It runs
independently from the sprinkler controller and shutdown-button services.

## Recovered wiring and MQTT behavior

The legacy controller used:

- BCM GPIO 4, physical header pin 7
- Internal pull-up, with the reed switch connected between GPIO 4 and ground
- Open circuit: publish `ON`
- Closed circuit: publish `OFF`
- Topic: `toggle/garage_door/state`
- MQTT port 1883
- Non-retained QoS 0 messages

The modern service preserves these defaults, publishes the current state at
startup, publishes only when the state changes, and retries after broker or
network failures. GPIO Zero debounce defaults to 0.1 seconds.

## Install

From the Pi Sprinkler Timer repository checkout:

```bash
sudo ./scripts/install-garage-door-monitor.sh
```

The installer explains the service, installs GPIO Zero, `lgpio`, and Paho MQTT,
then asks for the MQTT username and password through unlimited masked prompts.
Credentials are saved only in
`/etc/pi-sprinkler-garage-door/garage-door.ini`, with mode `0640` and access
limited to root and the dedicated service account. The installer refuses to
start if the selected pin is assigned to a sprinkler station or shutdown
button.

The recovered broker address and topic are the defaults. Override non-secret
values when needed:

```bash
sudo ./scripts/install-garage-door-monitor.sh \
    --mqtt-host mqtt.example.internal \
    --topic toggle/garage_door/state
```

Do not pass MQTT credentials as command-line arguments. Use `--retain` only if
Home Assistant should receive the most recently published state immediately
after reconnecting. The legacy installation did not retain messages.

## Operate and troubleshoot

```bash
systemctl status pi-sprinkler-garage-door.service --no-pager -l
journalctl -u pi-sprinkler-garage-door.service -n 100 --no-pager
sudo systemctl restart pi-sprinkler-garage-door.service
```

Edit settings with:

```bash
sudoedit /etc/pi-sprinkler-garage-door/garage-door.ini
sudo systemctl restart pi-sprinkler-garage-door.service
```

The installer preserves an existing configuration on reruns. If it detects the
exact legacy `/home/pi/reed_switch.py` service or startup entry, it backs up and
disables that listener before starting the new service. It does not alter the
sprinkler controller or shutdown-button service.
