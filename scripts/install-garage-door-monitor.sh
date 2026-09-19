#!/usr/bin/env bash
set -Eeuo pipefail

readonly SERVICE_NAME="pi-sprinkler-garage-door.service"
readonly SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}"
readonly PROGRAM_FILE="/usr/local/libexec/pi-sprinkler-garage-door.py"
readonly CONFIG_DIRECTORY="/etc/pi-sprinkler-garage-door"
readonly CONFIG_FILE="${CONFIG_DIRECTORY}/garage-door.ini"
readonly SERVICE_USER="garage-door-monitor"
readonly BACKUP_DIRECTORY="/var/backups/open-sprinkler"

gpio_pin=4
bounce_time=0.1
mqtt_host="192.168.0.3"
mqtt_port=1883
mqtt_topic="toggle/garage_door/state"
retain=false
start_service=true

usage() {
    cat <<'EOF'
Usage: sudo ./scripts/install-garage-door-monitor.sh [options]

Install the garage-door reed-switch MQTT monitor as a systemd service.

Options:
  --pin BCM_PIN       Reed-switch GPIO in BCM numbering (default: 4)
  --bounce-time SEC   GPIO Zero debounce interval (default: 0.1)
  --mqtt-host HOST    MQTT broker hostname or IP (default: 192.168.0.3)
  --mqtt-port PORT    MQTT broker port (default: 1883)
  --topic TOPIC       MQTT state topic (default: toggle/garage_door/state)
  --retain            Publish retained state messages (legacy default: off)
  --no-start          Install and validate, but leave the service stopped
  -h, --help          Show this help

MQTT credentials are collected through unlimited masked system prompts. They
are never accepted on the command line or printed by the installer.
EOF
}

log() { printf '[garage-door] %s\n' "$*"; }
fail() { printf '[garage-door] ERROR: %s\n' "$*" >&2; exit 1; }

while (($#)); do
    case "$1" in
        --pin)
            (($# >= 2)) || fail "--pin requires a BCM GPIO number"
            gpio_pin=$2
            shift 2
            ;;
        --bounce-time)
            (($# >= 2)) || fail "--bounce-time requires seconds"
            bounce_time=$2
            shift 2
            ;;
        --mqtt-host)
            (($# >= 2)) || fail "--mqtt-host requires a value"
            mqtt_host=$2
            shift 2
            ;;
        --mqtt-port)
            (($# >= 2)) || fail "--mqtt-port requires a value"
            mqtt_port=$2
            shift 2
            ;;
        --topic)
            (($# >= 2)) || fail "--topic requires a value"
            mqtt_topic=$2
            shift 2
            ;;
        --retain)
            retain=true
            shift
            ;;
        --no-start)
            start_service=false
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "unknown option: $1"
            ;;
    esac
done

[[ ${EUID} -eq 0 ]] || fail "run this installer with sudo"
[[ ${gpio_pin} =~ ^[0-9]+$ ]] && ((gpio_pin >= 0 && gpio_pin <= 27)) \
    || fail "--pin must be a BCM GPIO number from 0 through 27"
[[ ${bounce_time} =~ ^[0-9]+([.][0-9]+)?$ ]] || fail "--bounce-time must be zero or greater"
[[ -n ${mqtt_host} ]] || fail "--mqtt-host must not be empty"
[[ ${mqtt_port} =~ ^[0-9]+$ ]] && ((mqtt_port >= 1 && mqtt_port <= 65535)) \
    || fail "--mqtt-port must be from 1 through 65535"
[[ -n ${mqtt_topic} ]] || fail "--topic must not be empty"
command -v apt-get >/dev/null || fail "this installer requires Raspberry Pi OS or Debian"
command -v systemctl >/dev/null || fail "systemd is required"
command -v systemd-ask-password >/dev/null || fail "systemd-ask-password is required"

SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SOURCE_DIRECTORY=$(cd -- "${SCRIPT_DIRECTORY}/.." && pwd)
[[ -f "${SOURCE_DIRECTORY}/scripts/garage_door_monitor.py" ]] \
    || fail "run this script from the repository checkout"

log "Installing GPIO Zero, lgpio, and the Paho MQTT client"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 python3-gpiozero python3-lgpio python3-paho-mqtt

if ! getent group "${SERVICE_USER}" >/dev/null; then
    groupadd --system "${SERVICE_USER}"
fi
if ! getent passwd "${SERVICE_USER}" >/dev/null; then
    useradd --system --gid "${SERVICE_USER}" --groups gpio \
        --home-dir /nonexistent --shell /usr/sbin/nologin "${SERVICE_USER}"
else
    usermod --append --groups gpio "${SERVICE_USER}"
fi

if [[ -f "${CONFIG_FILE}" ]]; then
    gpio_pin=$(python3 - "${CONFIG_FILE}" <<'PY'
import configparser
import sys

parser = configparser.ConfigParser(interpolation=None)
parser.read(sys.argv[1], encoding="utf-8")
print(parser.getint("garage-door", "gpio_pin", fallback=4))
PY
    )
fi

if [[ -f /etc/open-sprinkler/open-sprinkler.ini ]] && python3 - /etc/open-sprinkler/open-sprinkler.ini "${gpio_pin}" <<'PY'
import configparser
import sys

parser = configparser.ConfigParser(interpolation=None)
parser.read(sys.argv[1], encoding="utf-8")
pins = {
    int(value.strip())
    for value in parser.get("Station GPIOs", "pins", fallback="").split(",")
    if value.strip()
}
raise SystemExit(0 if int(sys.argv[2]) in pins else 1)
PY
then
    fail "BCM GPIO ${gpio_pin} is already assigned to a sprinkler station"
fi

if [[ -f /etc/default/open-sprinkler-shutdown-button ]]; then
    shutdown_pin=$(sed -n -E 's/^[[:space:]]*BUTTON_BCM_PIN=([0-9]+)[[:space:]]*$/\1/p' /etc/default/open-sprinkler-shutdown-button | tail -n 1)
    if [[ -n ${shutdown_pin} && ${shutdown_pin} == "${gpio_pin}" ]]; then
        fail "BCM GPIO ${gpio_pin} is already assigned to the shutdown button"
    fi
fi

log "Installing the monitor and its protected configuration"
install -d -m 0755 /usr/local/libexec
install -m 0755 "${SOURCE_DIRECTORY}/scripts/garage_door_monitor.py" "${PROGRAM_FILE}"
install -d -m 0750 -o root -g "${SERVICE_USER}" "${CONFIG_DIRECTORY}"

if [[ -e "${CONFIG_FILE}" ]]; then
    log "Preserving existing ${CONFIG_FILE}"
else
    printf '%s\n' \
        "The MQTT account lets this service publish the garage-door state." \
        "Enter the broker username and password at the masked prompts." \
        "The values are stored only in ${CONFIG_FILE}, readable by root and the service account."
    mqtt_username=$(systemd-ask-password --timeout=0 "Garage door MQTT username:")
    mqtt_password=$(systemd-ask-password --timeout=0 "Garage door MQTT password:")
    [[ -n ${mqtt_username} ]] || fail "MQTT username must not be empty"
    [[ -n ${mqtt_password} ]] || fail "MQTT password must not be empty"

    temporary_config=$(mktemp)
    trap 'rm -f "${temporary_config:-}"' EXIT
    umask 077
    {
        printf '[garage-door]\n'
        printf 'gpio_pin = %s\n' "${gpio_pin}"
        printf 'bounce_time = %s\n' "${bounce_time}"
        printf 'mqtt_host = %s\n' "${mqtt_host}"
        printf 'mqtt_port = %s\n' "${mqtt_port}"
        printf 'mqtt_username = %s\n' "${mqtt_username}"
        printf 'mqtt_password = %s\n' "${mqtt_password}"
        printf 'mqtt_topic = %s\n' "${mqtt_topic}"
        printf 'open_payload = ON\n'
        printf 'closed_payload = OFF\n'
        printf 'retain = %s\n' "${retain}"
        printf 'retry_seconds = 5\n'
    } >"${temporary_config}"
    install -m 0640 -o root -g "${SERVICE_USER}" "${temporary_config}" "${CONFIG_FILE}"
    rm -f "${temporary_config}"
    trap - EXIT
fi

python3 "${PROGRAM_FILE}" --config "${CONFIG_FILE}" --check-config

log "Installing and validating the systemd unit"
install -m 0644 "${SOURCE_DIRECTORY}/systemd/${SERVICE_NAME}" "${SERVICE_FILE}"
systemd-analyze verify "${SERVICE_FILE}"

legacy_detected=false
if [[ -f /home/pi/reed_switch.py ]] || [[ -e /etc/systemd/system/reed_switch.service ]]; then
    legacy_detected=true
fi
if [[ -f /etc/rc.local ]] && grep -Eq '^[[:space:]]*[^#].*/home/pi/reed_switch[.]py([[:space:]]|&|$)' /etc/rc.local; then
    legacy_detected=true
fi

if [[ "${legacy_detected}" == true ]]; then
    log "Backing up and disabling the exact legacy reed-switch listener"
    install -d -m 0700 "${BACKUP_DIRECTORY}"
    timestamp=$(date +%Y%m%d-%H%M%S)
    [[ -f /home/pi/reed_switch.py ]] \
        && cp -a /home/pi/reed_switch.py "${BACKUP_DIRECTORY}/reed_switch.py.${timestamp}"
    [[ -f /etc/systemd/system/reed_switch.service ]] \
        && cp -a /etc/systemd/system/reed_switch.service "${BACKUP_DIRECTORY}/reed_switch.service.${timestamp}"
    [[ -f /etc/rc.local ]] && cp -a /etc/rc.local "${BACKUP_DIRECTORY}/rc.local.${timestamp}"
    systemctl disable --now reed_switch.service >/dev/null 2>&1 || true
    if [[ -f /etc/rc.local ]]; then
        sed -i -E '/^[[:space:]]*[^#].*\/home\/pi\/reed_switch[.]py([[:space:]]|&|$)/ s/^/# Disabled by pi-sprinkler-garage-door: /' /etc/rc.local
    fi
fi

legacy_pids=$(ps -eo pid=,comm=,args= | awk '$2 ~ /^python(2|3)?([.][0-9]+)?$/ && $0 ~ /(^|[[:space:]])(\/usr\/bin\/)?python(2|3)?([.][0-9]+)?[[:space:]]+\/home\/pi\/reed_switch[.]py([[:space:]]|$)/ {print $1}')
if [[ -n "${legacy_pids}" ]]; then
    log "Stopping the exact legacy reed-switch process: ${legacy_pids//$'\n'/ }"
    kill ${legacy_pids} 2>/dev/null || true
    sleep 1
fi
remaining=$(ps -eo pid=,comm=,args= | awk '$2 ~ /^python(2|3)?([.][0-9]+)?$/ && $0 ~ /(^|[[:space:]])(\/usr\/bin\/)?python(2|3)?([.][0-9]+)?[[:space:]]+\/home\/pi\/reed_switch[.]py([[:space:]]|$)/ {print $1}')
[[ -z "${remaining}" ]] || fail "legacy reed-switch process is still running; refusing to start a duplicate"

log "Reloading systemd and applying the startup policy"
systemctl daemon-reload
if [[ "${start_service}" == true ]]; then
    systemctl enable --now "${SERVICE_NAME}"
    systemctl is-active --quiet "${SERVICE_NAME}" \
        || { systemctl --no-pager --full status "${SERVICE_NAME}" >&2; fail "garage-door service did not become active"; }
    log "Installed and running ${SERVICE_NAME} on BCM GPIO ${gpio_pin}"
else
    systemctl disable --now "${SERVICE_NAME}" >/dev/null 2>&1 || true
    log "Installed ${SERVICE_NAME}; it remains stopped because --no-start was selected"
fi
