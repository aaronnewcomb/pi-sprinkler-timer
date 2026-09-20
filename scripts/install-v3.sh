#!/usr/bin/env bash
set -Eeuo pipefail

readonly DEFAULT_REPOSITORY="https://github.com/aaronnewcomb/pi-sprinkler-timer.git"
readonly DEFAULT_REF="v3.0.0"
readonly SERVICE_NAME="pi-sprinkler.service"
readonly CONTROLLER_HEALTH_TIMEOUT_SECONDS=90
readonly APPLICATION_ROOT="/opt/pi-sprinkler"
readonly SOURCE_DIRECTORY="${APPLICATION_ROOT}/source"
readonly VIRTUAL_ENVIRONMENT="${APPLICATION_ROOT}/.venv"
readonly CONFIGURATION_DIRECTORY="/etc/pi-sprinkler"
readonly CONFIGURATION_FILE="${CONFIGURATION_DIRECTORY}/pi-sprinkler.ini"
readonly TOKEN_FILE="${CONFIGURATION_DIRECTORY}/api-token"
readonly SERVICE_FILE="/etc/systemd/system/pi-sprinkler.service"
readonly PROXY_AVAILABLE="/etc/lighttpd/conf-available/99-pi-sprinkler.conf"
readonly PROXY_ENABLED="/etc/lighttpd/conf-enabled/99-pi-sprinkler.conf"
readonly TLS_AVAILABLE="/etc/lighttpd/conf-available/98-pi-sprinkler-tls.conf"
readonly TLS_ENABLED="/etc/lighttpd/conf-enabled/98-pi-sprinkler-tls.conf"
readonly CERTIFICATE_DIRECTORY="/etc/lighttpd/certs/pi-sprinkler"
readonly MKCERT_CA_DIRECTORY="${CONFIGURATION_DIRECTORY}/mkcert-ca"
readonly LEGACY_CONFIGURATION_DIRECTORY="/etc/open-sprinkler"
readonly LEGACY_CONFIGURATION_FILE="${LEGACY_CONFIGURATION_DIRECTORY}/open-sprinkler.ini"
readonly LEGACY_TOKEN_FILE="${LEGACY_CONFIGURATION_DIRECTORY}/api-token"
readonly LEGACY_DATABASE_FILE="/var/lib/open-sprinkler/open-sprinkler.db"
readonly LEGACY_CERTIFICATE_DIRECTORY="/etc/lighttpd/certs/open-sprinkler"
readonly LEGACY_MKCERT_CA_DIRECTORY="${LEGACY_CONFIGURATION_DIRECTORY}/mkcert-ca"
readonly MIGRATION_BACKUP_DIRECTORY="/var/backups/pi-sprinkler/name-migration"
readonly -a LEGACY_SERVICE_NAMES=(
    "open-sprinkler-v3.service"
    "open-sprinkler.service"
)
readonly -a LEGACY_LIGHTTPD_PATHS=(
    "/etc/lighttpd/conf-enabled/99-open-sprinkler-v3.conf"
    "/etc/lighttpd/conf-available/99-open-sprinkler-v3.conf"
    "/etc/lighttpd/conf-enabled/98-open-sprinkler-tls.conf"
    "/etc/lighttpd/conf-available/98-open-sprinkler-tls.conf"
)

repository="${PI_SPRINKLER_REPOSITORY:-${DEFAULT_REPOSITORY}}"
source_ref="${PI_SPRINKLER_REF:-${DEFAULT_REF}}"
access_mode=""
tls_hostname=""
tls_ip=""
run_tests=true
start_service=true
valve_power_disconnected=false
full_upgrade=false

usage() {
    cat <<'EOF'
Install Pi Sprinkler Timer on Raspberry Pi OS.

Usage:
  sudo ./scripts/install-v3.sh --mode http [options]
  sudo ./scripts/install-v3.sh --mode https --hostname NAME --ip ADDRESS [options]

Options:
  --mode http|https     Required browser access mode.
  --hostname NAME       Stable controller hostname for HTTPS certificates.
  --ip ADDRESS          Stable controller IP for HTTPS certificates.
  --ref REF             Git tag or branch to install.
  --repository URL      Git repository URL.
  --skip-tests          Skip the application test suite.
  --full-upgrade        Run apt full-upgrade before installing packages.
  --no-start            Install and validate, but leave the controller disabled.
  --start               Start the controller after validation (the default).
  --valve-power-disconnected
                        Skip the interactive relay-power safety confirmation.
  -h, --help            Show this help.

The installer never overwrites an existing controller configuration or valid
API token. By default it confirms valve power is disconnected, then enables
and starts the web proxy and controller. Use --no-start for a staged install.
EOF
}

log() {
    printf '\n==> %s\n' "$*"
}

stage() {
    local number="$1"
    local total="$2"
    local title="$3"
    local description="$4"
    printf '\n============================================================\n'
    printf 'Stage %s of %s: %s\n' "${number}" "${total}" "${title}"
    printf '%s\n' "${description}"
    printf '============================================================\n'
}

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

enable_lighttpd_configuration() {
    local available_name="$1"
    local enabled_path="$2"
    if [[ -L "${enabled_path}" ]]; then
        [[ "$(readlink -f "${enabled_path}")" == "/etc/lighttpd/conf-available/${available_name}" ]] || \
            fail "Unexpected symlink at ${enabled_path}"
    elif [[ -e "${enabled_path}" ]]; then
        fail "Refusing to replace existing non-symlink ${enabled_path}"
    else
        ln -s "../conf-available/${available_name}" "${enabled_path}"
    fi
}

archive_legacy_path() {
    local path="$1"
    local destination
    if [[ ! -e "${path}" && ! -L "${path}" ]]; then
        return
    fi
    destination="${MIGRATION_BACKUP_DIRECTORY}${path}"
    install -d -m 0700 -o root -g root "$(dirname -- "${destination}")"
    [[ ! -e "${destination}" && ! -L "${destination}" ]] || \
        fail "Migration backup already exists: ${destination}"
    mv -- "${path}" "${destination}"
    log "Archived legacy path ${path}"
}

set_secure_cookies() {
    local desired="$1"
    python3 - "${CONFIGURATION_FILE}" "${desired}" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
desired = sys.argv[2]
text = path.read_text(encoding="utf-8")
updated, count = re.subn(
    r"(?m)^(\s*secure_cookies\s*=\s*)(?:true|false)(\s*)$",
    rf"\g<1>{desired}\g<2>",
    text,
)
if count != 1:
    raise SystemExit(f"Expected one secure_cookies setting in {path}, found {count}")
path.write_text(updated, encoding="utf-8")
PY
}

token_is_valid() {
    local path="${1:-${TOKEN_FILE}}"
    python3 - "${path}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
try:
    token = path.read_text(encoding="utf-8").strip()
except (OSError, UnicodeError):
    raise SystemExit(1)
raise SystemExit(0 if len(token) >= 32 else 1)
PY
}

migrate_legacy_controller_data() {
    local new_database_file="/var/lib/pi-sprinkler/pi-sprinkler.db"

    if [[ ! -e "${CONFIGURATION_FILE}" && -f "${LEGACY_CONFIGURATION_FILE}" ]]; then
        log "Migrating the existing controller configuration to ${CONFIGURATION_FILE}"
        install -m 0640 -o root -g pi-sprinkler \
            "${LEGACY_CONFIGURATION_FILE}" "${CONFIGURATION_FILE}"
        python3 - "${CONFIGURATION_FILE}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace(
    "/var/lib/open-sprinkler/open-sprinkler.db",
    "/var/lib/pi-sprinkler/pi-sprinkler.db",
)
path.write_text(text, encoding="utf-8")
PY
    fi

    if ! token_is_valid && token_is_valid "${LEGACY_TOKEN_FILE}"; then
        log "Migrating the existing API token to ${TOKEN_FILE}"
        install -m 0640 -o root -g pi-sprinkler \
            "${LEGACY_TOKEN_FILE}" "${TOKEN_FILE}"
    fi

    if [[ ! -e "${new_database_file}" && -f "${LEGACY_DATABASE_FILE}" ]]; then
        log "Migrating schedules and run history to ${new_database_file}"
        install -d -m 0750 -o pi-sprinkler -g pi-sprinkler \
            "$(dirname -- "${new_database_file}")"
        python3 - "${LEGACY_DATABASE_FILE}" "${new_database_file}" <<'PY'
from pathlib import Path
import sqlite3
import sys

source_path = Path(sys.argv[1]).resolve()
destination_path = Path(sys.argv[2])
source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
destination = sqlite3.connect(destination_path)
try:
    source.backup(destination)
finally:
    destination.close()
    source.close()
PY
        chown pi-sprinkler:pi-sprinkler "${new_database_file}"
        chmod 0640 "${new_database_file}"
    fi

    if [[ ! -e "${CERTIFICATE_DIRECTORY}/fullchain.pem" && \
          ! -e "${CERTIFICATE_DIRECTORY}/privkey.pem" && \
          -s "${LEGACY_CERTIFICATE_DIRECTORY}/fullchain.pem" && \
          -s "${LEGACY_CERTIFICATE_DIRECTORY}/privkey.pem" ]]; then
        log "Migrating the existing TLS certificate"
        install -d -m 0700 -o root -g root "${CERTIFICATE_DIRECTORY}"
        install -m 0644 -o root -g root \
            "${LEGACY_CERTIFICATE_DIRECTORY}/fullchain.pem" \
            "${CERTIFICATE_DIRECTORY}/fullchain.pem"
        install -m 0600 -o root -g root \
            "${LEGACY_CERTIFICATE_DIRECTORY}/privkey.pem" \
            "${CERTIFICATE_DIRECTORY}/privkey.pem"
    fi

    if [[ ! -e "${MKCERT_CA_DIRECTORY}/rootCA.pem" && \
          ! -e "${MKCERT_CA_DIRECTORY}/rootCA-key.pem" && \
          -s "${LEGACY_MKCERT_CA_DIRECTORY}/rootCA.pem" && \
          -s "${LEGACY_MKCERT_CA_DIRECTORY}/rootCA-key.pem" ]]; then
        log "Migrating the existing local certificate authority"
        install -d -m 0700 -o root -g root "${MKCERT_CA_DIRECTORY}"
        install -m 0644 -o root -g root \
            "${LEGACY_MKCERT_CA_DIRECTORY}/rootCA.pem" \
            "${MKCERT_CA_DIRECTORY}/rootCA.pem"
        install -m 0600 -o root -g root \
            "${LEGACY_MKCERT_CA_DIRECTORY}/rootCA-key.pem" \
            "${MKCERT_CA_DIRECTORY}/rootCA-key.pem"
    fi
}

retire_legacy_controller_units() {
    local legacy_service
    for legacy_service in "${LEGACY_SERVICE_NAMES[@]}"; do
        systemctl disable "${legacy_service}" >/dev/null 2>&1 || true
        archive_legacy_path "/etc/systemd/system/${legacy_service}"
    done
}

retire_legacy_lighttpd_configuration() {
    local path
    for path in "${LEGACY_LIGHTTPD_PATHS[@]}"; do
        archive_legacy_path "${path}"
    done
}

fail_controller_health_check() {
    local reason="$1"
    systemctl --no-pager --full status "${SERVICE_NAME}" >&2 || true
    systemctl show "${SERVICE_NAME}" \
        --property=ActiveState,SubState,Result,NRestarts,ExecMainCode,ExecMainStatus \
        --no-pager >&2 || true
    journalctl -u "${SERVICE_NAME}" -n 80 --no-pager >&2 || true
    curl --fail --show-error --max-time 2 \
        http://127.0.0.1:8000/api/v1/health >/dev/null || true
    systemctl disable --now "${SERVICE_NAME}" >/dev/null 2>&1 || true
    fail "${reason}; ${SERVICE_NAME} was stopped and disabled"
}

wait_for_controller_health() {
    local deadline=$((SECONDS + CONTROLLER_HEALTH_TIMEOUT_SECONDS))
    while ((SECONDS < deadline)); do
        if curl --fail --silent --max-time 2 \
            http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
            printf 'Controller health check passed.\n'
            return 0
        fi
        if systemctl is-failed --quiet "${SERVICE_NAME}"; then
            fail_controller_health_check \
                "Controller service failed before its health endpoint became ready"
        fi
        sleep 1
    done
    fail_controller_health_check \
        "Controller health endpoint did not become ready within ${CONTROLLER_HEALTH_TIMEOUT_SECONDS} seconds"
}

while (($#)); do
    case "$1" in
        --mode)
            (($# >= 2)) || fail "--mode requires a value"
            access_mode="$2"
            shift 2
            ;;
        --hostname)
            (($# >= 2)) || fail "--hostname requires a value"
            tls_hostname="$2"
            shift 2
            ;;
        --ip)
            (($# >= 2)) || fail "--ip requires a value"
            tls_ip="$2"
            shift 2
            ;;
        --ref)
            (($# >= 2)) || fail "--ref requires a value"
            source_ref="$2"
            shift 2
            ;;
        --repository)
            (($# >= 2)) || fail "--repository requires a value"
            repository="$2"
            shift 2
            ;;
        --skip-tests)
            run_tests=false
            shift
            ;;
        --full-upgrade)
            full_upgrade=true
            shift
            ;;
        --start)
            start_service=true
            shift
            ;;
        --no-start)
            start_service=false
            shift
            ;;
        --valve-power-disconnected)
            valve_power_disconnected=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "Unknown option: $1"
            ;;
    esac
done

[[ "${EUID}" -eq 0 ]] || fail "Run this installer with sudo"
[[ "${access_mode}" == "http" || "${access_mode}" == "https" ]] || \
    fail "Choose --mode http or --mode https"
[[ "${repository}" != -* && "${source_ref}" != -* ]] || \
    fail "Repository and Git ref values must not begin with a dash"
if [[ "${access_mode}" == "https" ]]; then
    [[ -n "${tls_hostname}" && -n "${tls_ip}" ]] || \
        fail "HTTPS mode requires --hostname and --ip"
    [[ "${tls_hostname}" != -* && "${tls_ip}" != -* ]] || \
        fail "TLS hostname and IP values must not begin with a dash"
fi

stage 1 8 "Safety and platform checks" \
    "Verifying this is a Raspberry Pi and confirming that relay-controlled valve power is safe before controller startup."
command -v apt-get >/dev/null || fail "This installer requires Raspberry Pi OS or Debian"
[[ -r /proc/device-tree/model ]] || fail "Raspberry Pi hardware was not detected"
grep -q "Raspberry Pi" /proc/device-tree/model || fail "Raspberry Pi hardware was not detected"
for controller_service in "${SERVICE_NAME}" "${LEGACY_SERVICE_NAMES[@]}"; do
    if systemctl is-active --quiet "${controller_service}"; then
        fail "The controller service ${controller_service} is active. Stop it before installing or updating:

  sudo systemctl stop ${controller_service}

Then rerun this installer with the same options."
    fi
done

if [[ "${start_service}" == true && "${valve_power_disconnected}" != true ]]; then
    cat <<'EOF'
The installer will enable and start GPIO control when installation finishes.
Disconnect the 24 VAC valve transformer now. This prevents an unexpected relay
state or configuration mistake from opening a valve during initial startup.
EOF
    [[ -t 0 ]] || fail \
        "Interactive safety confirmation requires a terminal; use --valve-power-disconnected only after physically disconnecting valve power"
    read -r -p "Type DISCONNECTED to confirm valve power is disconnected: " relay_confirmation
    [[ "${relay_confirmation}" == "DISCONNECTED" ]] || \
        fail "Valve-power confirmation was not accepted"
    valve_power_disconnected=true
fi

stage 2 8 "Operating-system packages" \
    "Refreshing APT metadata and installing lighttpd, Python, GPIO Zero, lgpio, and the tools required by the selected HTTP or HTTPS mode."
export DEBIAN_FRONTEND=noninteractive
apt-get update
if [[ "${full_upgrade}" == true ]]; then
    apt-get full-upgrade -y
fi
packages=(
    git
    lighttpd
    openssl
    python3
    python3-gpiozero
    python3-lgpio
    python3-venv
)
if [[ "${access_mode}" == "https" ]]; then
    packages+=(libnss3-tools lighttpd-mod-openssl mkcert)
fi
apt-get install -y "${packages[@]}"

stage 3 8 "Application and Python environment" \
    "Installing source ref ${source_ref} under /opt and building an isolated Python environment while retaining access to the system GPIO libraries."
install -d -m 0755 -o root -g root "${APPLICATION_ROOT}"
if [[ -d "${SOURCE_DIRECTORY}/.git" ]]; then
    [[ -z "$(git -C "${SOURCE_DIRECTORY}" status --porcelain)" ]] || \
        fail "Source checkout has local changes: ${SOURCE_DIRECTORY}"
    git -C "${SOURCE_DIRECTORY}" fetch --tags origin \
        '+refs/heads/*:refs/remotes/origin/*'
    if git -C "${SOURCE_DIRECTORY}" rev-parse --verify --quiet \
        "refs/tags/${source_ref}" >/dev/null; then
        resolved_ref="refs/tags/${source_ref}"
    elif git -C "${SOURCE_DIRECTORY}" rev-parse --verify --quiet \
        "refs/remotes/origin/${source_ref}" >/dev/null; then
        resolved_ref="refs/remotes/origin/${source_ref}"
    elif git -C "${SOURCE_DIRECTORY}" rev-parse --verify --quiet \
        "${source_ref}^{commit}" >/dev/null; then
        resolved_ref="${source_ref}"
    else
        fail "Git ref was not found: ${source_ref}"
    fi
    git -C "${SOURCE_DIRECTORY}" checkout --detach "${resolved_ref}"
elif [[ -e "${SOURCE_DIRECTORY}" ]]; then
    fail "Refusing to replace non-Git path ${SOURCE_DIRECTORY}"
else
    git clone --branch "${source_ref}" --single-branch \
        "${repository}" "${SOURCE_DIRECTORY}"
fi

if [[ ! -x "${VIRTUAL_ENVIRONMENT}/bin/python3" ]]; then
    python3 -m venv --system-site-packages "${VIRTUAL_ENVIRONMENT}"
fi
"${VIRTUAL_ENVIRONMENT}/bin/pip" install "${SOURCE_DIRECTORY}"

stage 4 8 "Automated software tests" \
    "Running the controller, API, scheduler, GPIO-safety, web, and installer regression tests before any service is started."
if [[ "${run_tests}" == true ]]; then
    "${VIRTUAL_ENVIRONMENT}/bin/pip" install pytest httpx
    "${VIRTUAL_ENVIRONMENT}/bin/pytest" -q "${SOURCE_DIRECTORY}/tests"
else
    printf 'Tests skipped because --skip-tests was supplied.\n'
fi

stage 5 8 "Service account, configuration, and API token" \
    "Creating a restricted controller account, preserving existing settings, and collecting the saved browser and Home Assistant credential when needed."
if ! getent group pi-sprinkler >/dev/null; then
    groupadd --system pi-sprinkler
fi
if ! getent passwd pi-sprinkler >/dev/null; then
    useradd --system --gid pi-sprinkler --home-dir /var/lib/pi-sprinkler \
        --shell /usr/sbin/nologin pi-sprinkler
fi
getent group gpio >/dev/null || fail "Required gpio group does not exist"
usermod --append --groups gpio pi-sprinkler
install -d -m 0750 -o root -g pi-sprinkler "${CONFIGURATION_DIRECTORY}"
migrate_legacy_controller_data
if [[ ! -e "${CONFIGURATION_FILE}" ]]; then
    install -m 0640 -o root -g pi-sprinkler \
        "${SOURCE_DIRECTORY}/pi-sprinkler.ini.example" \
        "${CONFIGURATION_FILE}"
fi
chown root:pi-sprinkler "${CONFIGURATION_FILE}"
chmod 0640 "${CONFIGURATION_FILE}"
if ! token_is_valid; then
    log "Creating the API token"
    cat <<'EOF'
The API token is the private password used by the browser dashboard and Home
Assistant to control this sprinkler system.

Before continuing:
  1. Use your password manager to generate a unique random password containing
     at least 32 characters. A length of 40 to 64 characters is recommended.
  2. Save it in the password manager with this controller's hostname or IP.
  3. Paste that same saved value at the masked prompt below.

The installer will not print the token, and the dashboard will not show it
later. Keep the saved copy for future browser logins and Home Assistant setup.
The masked prompt waits indefinitely. Press Ctrl+C if you need to stop; rerun
this installer later and it will safely return to this step.
EOF
    read -r -p "Press Enter after the API token is generated and safely saved: " _
    install -m 0640 -o root -g pi-sprinkler /dev/null "${TOKEN_FILE}"
    if ! systemd-ask-password --timeout=0 \
        "Paste the saved Pi Sprinkler Timer API token" >"${TOKEN_FILE}"; then
        install -m 0640 -o root -g pi-sprinkler /dev/null "${TOKEN_FILE}"
        fail "API token entry was cancelled; rerun the installer to resume"
    fi
fi
chown root:pi-sprinkler "${TOKEN_FILE}"
chmod 0640 "${TOKEN_FILE}"
token_is_valid || fail "API token must contain at least 32 characters: ${TOKEN_FILE}"

stage 6 8 "systemd controller service" \
    "Installing and validating the boot-time service definition that runs the controller with restricted permissions and GPIO-group access."
install -m 0644 "${SOURCE_DIRECTORY}/systemd/pi-sprinkler.service" \
    "${SERVICE_FILE}"
retire_legacy_controller_units
systemctl daemon-reload
systemd-analyze verify "${SERVICE_FILE}"

stage 7 8 "Web proxy and transport security" \
    "Configuring lighttpd to expose the loopback-only application to the LAN using the selected HTTP or HTTPS mode, then validating the complete web-server configuration."
retire_legacy_lighttpd_configuration
install -m 0644 "${SOURCE_DIRECTORY}/lighttpd/99-pi-sprinkler.conf" \
    "${PROXY_AVAILABLE}"
enable_lighttpd_configuration "99-pi-sprinkler.conf" "${PROXY_ENABLED}"

if [[ "${access_mode}" == "http" ]]; then
    [[ ! -e "${TLS_ENABLED}" ]] || \
        fail "TLS is already enabled; use --mode https or disable it deliberately"
    set_secure_cookies false
    printf '%s\n' \
        "WARNING: HTTP mode sends the API token unencrypted on the local network." \
        "Use only for short acceptance testing, then rotate the token and install TLS."
else
    set_secure_cookies true
    install -d -m 0700 -o root -g root "${CERTIFICATE_DIRECTORY}"
    install -d -m 0700 -o root -g root "${MKCERT_CA_DIRECTORY}"
    if [[ ! -e "${MKCERT_CA_DIRECTORY}/rootCA.pem" && \
          ! -e "${MKCERT_CA_DIRECTORY}/rootCA-key.pem" ]]; then
        CAROOT="${MKCERT_CA_DIRECTORY}" mkcert -install
    elif [[ ! -s "${MKCERT_CA_DIRECTORY}/rootCA.pem" || \
            ! -s "${MKCERT_CA_DIRECTORY}/rootCA-key.pem" ]]; then
        fail "mkcert CA is incomplete in ${MKCERT_CA_DIRECTORY}"
    fi
    certificate="${CERTIFICATE_DIRECTORY}/fullchain.pem"
    private_key="${CERTIFICATE_DIRECTORY}/privkey.pem"
    if [[ ! -e "${certificate}" && ! -e "${private_key}" ]]; then
        CAROOT="${MKCERT_CA_DIRECTORY}" mkcert \
            -cert-file "${certificate}" \
            -key-file "${private_key}" \
            "${tls_hostname}" "${tls_ip}"
    elif [[ ! -s "${certificate}" || ! -s "${private_key}" ]]; then
        fail "TLS certificate pair is incomplete in ${CERTIFICATE_DIRECTORY}"
    fi
    chmod 0644 "${certificate}" "${MKCERT_CA_DIRECTORY}/rootCA.pem"
    chmod 0600 "${private_key}" "${MKCERT_CA_DIRECTORY}/rootCA-key.pem"
    if [[ ! -e "${TLS_AVAILABLE}" ]]; then
        install -m 0644 \
            "${SOURCE_DIRECTORY}/lighttpd/98-pi-sprinkler-tls.conf.example" \
            "${TLS_AVAILABLE}"
    fi
    enable_lighttpd_configuration "98-pi-sprinkler-tls.conf" "${TLS_ENABLED}"
    openssl x509 -in "${certificate}" -noout -subject -issuer -dates -ext subjectAltName
fi

lighttpd -tt -f /etc/lighttpd/lighttpd.conf
systemctl enable --now lighttpd
systemctl restart lighttpd
systemctl --no-pager --full status lighttpd

stage 8 8 "Controller activation and health verification" \
    "Applying the selected startup policy, checking the systemd state, and verifying the controller's loopback health endpoint."
if [[ "${start_service}" == true ]]; then
    [[ "${valve_power_disconnected}" == true ]] || \
        fail "Internal safety check failed: valve power was not confirmed disconnected"
    log "Enabling and starting the controller with valve power confirmed disconnected"
    systemctl enable --now "${SERVICE_NAME}"
    systemctl --no-pager --full status "${SERVICE_NAME}"
    wait_for_controller_health
else
    systemctl disable --now "${SERVICE_NAME}"
    log "The --no-start option left the GPIO service stopped and disabled"
fi

printf '\nInstallation complete.\n'
printf '  Controller configuration: %s\n' "${CONFIGURATION_FILE}"
printf '  API token file: %s (contents were not displayed)\n' "${TOKEN_FILE}"
if [[ "${access_mode}" == "https" ]]; then
    printf '  Web address: https://%s/\n' "${tls_hostname}"
    printf '  Client trust certificate: %s/rootCA.pem\n' "${MKCERT_CA_DIRECTORY}"
else
    primary_ip="$(hostname -I | awk '{print $1}')"
    printf '  Web address: http://%s/\n' "${primary_ip:-CONTROLLER-IP}"
    printf '  Security mode: temporary unencrypted HTTP on the trusted LAN\n'
fi
if [[ "${start_service}" == true ]]; then
    printf '  Controller service: enabled and running\n'
    printf '  Safety: keep valve power disconnected until relay acceptance passes\n'
else
    printf '  Controller service: disabled and stopped (--no-start)\n'
fi
