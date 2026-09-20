#!/usr/bin/env bash
set -Eeuo pipefail

readonly SERVICE_NAME="open-sprinkler-shutdown-button.service"
readonly SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}"
readonly PROGRAM_FILE="/usr/local/libexec/open-sprinkler-shutdown-button.py"
readonly DEFAULTS_FILE="/etc/default/open-sprinkler-shutdown-button"
readonly BACKUP_DIRECTORY="/var/backups/open-sprinkler"

button_pin=3
bounce_time=0.2
start_service=true
keep_legacy=false

usage() {
    cat <<'EOF'
Usage: sudo ./scripts/install-shutdown-button.sh [options]

Install the GPIO shutdown-button listener as a systemd service.

Options:
  --pin BCM_PIN       Button GPIO in BCM numbering (default: 3, physical pin 5)
  --bounce-time SEC   GPIO Zero debounce interval (default: 0.2)
  --no-start          Install and validate, but leave the service stopped
  --keep-legacy       Do not disable rc.local/SysV legacy listeners
  -h, --help          Show this help

The normal install backs up and disables only the known legacy shutdown-button
entries, then enables and starts the new service. It never modifies sprinkler
configuration or sprinkler relay services.
EOF
}

log() { printf '[shutdown-button] %s\n' "$*"; }
fail() { printf '[shutdown-button] ERROR: %s\n' "$*" >&2; exit 1; }

while (($#)); do
    case "$1" in
        --pin)
            (($# >= 2)) || fail "--pin requires a BCM GPIO number"
            button_pin=$2
            shift 2
            ;;
        --bounce-time)
            (($# >= 2)) || fail "--bounce-time requires seconds"
            bounce_time=$2
            shift 2
            ;;
        --no-start)
            start_service=false
            shift
            ;;
        --keep-legacy)
            keep_legacy=true
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
[[ ${button_pin} =~ ^[0-9]+$ ]] && ((button_pin >= 0 && button_pin <= 27)) \
    || fail "--pin must be a BCM GPIO number from 0 through 27"
[[ ${bounce_time} =~ ^[0-9]+([.][0-9]+)?$ ]] || fail "--bounce-time must be zero or greater"
command -v apt-get >/dev/null || fail "this installer requires Raspberry Pi OS or Debian"
command -v systemctl >/dev/null || fail "systemd is required"

SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SOURCE_DIRECTORY=$(cd -- "${SCRIPT_DIRECTORY}/.." && pwd)
[[ -f "${SOURCE_DIRECTORY}/scripts/shutdown_button.py" ]] \
    || fail "run this script from the repository checkout"

log "Installing GPIO Zero and the lgpio backend"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-gpiozero python3-lgpio

log "Installing the shutdown-button program and configuration"
install -d -m 0755 /usr/local/libexec
install -m 0755 "${SOURCE_DIRECTORY}/scripts/shutdown_button.py" "${PROGRAM_FILE}"
if [[ -e "${DEFAULTS_FILE}" ]]; then
    log "Preserving existing ${DEFAULTS_FILE}"
else
    install -d -m 0755 /etc/default
    umask 022
    printf '# BCM GPIO number for the shutdown button. Physical pin 5 is BCM 3.\nBUTTON_BCM_PIN=%s\nBUTTON_BOUNCE_TIME=%s\n' \
        "${button_pin}" "${bounce_time}" >"${DEFAULTS_FILE}"
    chmod 0644 "${DEFAULTS_FILE}"
fi

log "Installing and validating the systemd unit"
install -m 0644 "${SOURCE_DIRECTORY}/systemd/open-sprinkler-shutdown-button.service" "${SERVICE_FILE}"
systemd-analyze verify "${SERVICE_FILE}"

legacy_rc_local=false
legacy_sysv=false
if [[ -f /etc/rc.local ]] && grep -Eq '^[[:space:]]*[^#].*/home/(pi/scripts|anewcomb)/shutdown[.]py([[:space:]]|&|$)' /etc/rc.local; then
    legacy_rc_local=true
fi
if [[ -e /etc/init.d/pi_shutdown ]] || compgen -G '/etc/rc*.d/*pi_shutdown*' >/dev/null; then
    legacy_sysv=true
fi

if [[ "${keep_legacy}" == true ]]; then
    if [[ "${legacy_rc_local}" == true || "${legacy_sysv}" == true ]]; then
        if [[ "${start_service}" == true ]]; then
            fail "legacy listener detected; remove it or use the default migration instead of --keep-legacy"
        fi
        log "Leaving legacy listener entries unchanged because --keep-legacy was selected"
    fi
else
    if [[ "${legacy_rc_local}" == true || "${legacy_sysv}" == true ]]; then
        log "Backing up legacy startup files before disabling the old listener"
        install -d -m 0700 "${BACKUP_DIRECTORY}"
        timestamp=$(date +%Y%m%d-%H%M%S)
        [[ -f /etc/rc.local ]] && cp -a /etc/rc.local "${BACKUP_DIRECTORY}/rc.local.${timestamp}"
        [[ -f /etc/init.d/pi_shutdown ]] && cp -a /etc/init.d/pi_shutdown "${BACKUP_DIRECTORY}/pi_shutdown.${timestamp}"
    fi
    if [[ "${legacy_rc_local}" == true ]]; then
        sed -i -E '/^[[:space:]]*[^#].*\/home\/(pi\/scripts|anewcomb)\/shutdown[.]py([[:space:]]|&|$)/ s/^/# Disabled by open-sprinkler-shutdown-button: /' /etc/rc.local
    fi
    if [[ "${legacy_sysv}" == true ]] && command -v update-rc.d >/dev/null; then
        update-rc.d pi_shutdown disable >/dev/null 2>&1 || true
    fi
fi

legacy_pids=$(ps -eo pid=,comm=,args= | awk '$2 ~ /^(python|python2|python3|sudo)$/ && $0 ~ /(^|[[:space:]])(sudo[[:space:]]+)?(\/usr\/bin\/)?python(2([.][0-9]+)?|3([.][0-9]+)?)?[[:space:]]+\/home\/(pi\/scripts|anewcomb)\/shutdown[.]py([[:space:]]|$)/ {print $1}')
if [[ -n "${legacy_pids}" ]]; then
    [[ "${keep_legacy}" == false ]] || fail "legacy shutdown-button process is still running"
    log "Stopping the exact legacy shutdown-button process: ${legacy_pids//$'\n'/ }"
    kill ${legacy_pids} 2>/dev/null || true
    sleep 1
    remaining=$(ps -eo pid=,comm=,args= | awk '$2 ~ /^(python|python2|python3|sudo)$/ && $0 ~ /(^|[[:space:]])(sudo[[:space:]]+)?(\/usr\/bin\/)?python(2([.][0-9]+)?|3([.][0-9]+)?)?[[:space:]]+\/home\/(pi\/scripts|anewcomb)\/shutdown[.]py([[:space:]]|$)/ {print $1}')
    [[ -z "${remaining}" ]] || fail "legacy listener did not stop; refusing to start a duplicate"
fi

log "Reloading systemd and applying the startup policy"
systemctl daemon-reload
if [[ "${start_service}" == true ]]; then
    systemctl enable --now "${SERVICE_NAME}"
    systemctl is-active --quiet "${SERVICE_NAME}" \
        || { systemctl --no-pager --full status "${SERVICE_NAME}" >&2; fail "shutdown-button service did not become active"; }
    log "Installed and running ${SERVICE_NAME} on BCM GPIO ${button_pin}"
else
    systemctl disable --now "${SERVICE_NAME}" >/dev/null 2>&1 || true
    log "Installed ${SERVICE_NAME}; it remains stopped because --no-start was selected"
fi
