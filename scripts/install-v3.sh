#!/usr/bin/env bash
set -Eeuo pipefail

readonly DEFAULT_REPOSITORY="https://github.com/aaronnewcomb/pi-sprinkler-timer.git"
readonly DEFAULT_REF="v3-ui-checkpoint-2026-09-17"
readonly APPLICATION_ROOT="/opt/open-sprinkler"
readonly SOURCE_DIRECTORY="${APPLICATION_ROOT}/source"
readonly VIRTUAL_ENVIRONMENT="${APPLICATION_ROOT}/.venv"
readonly CONFIGURATION_DIRECTORY="/etc/open-sprinkler"
readonly CONFIGURATION_FILE="${CONFIGURATION_DIRECTORY}/open-sprinkler.ini"
readonly TOKEN_FILE="${CONFIGURATION_DIRECTORY}/api-token"
readonly SERVICE_FILE="/etc/systemd/system/open-sprinkler-v3.service"
readonly PROXY_AVAILABLE="/etc/lighttpd/conf-available/99-open-sprinkler-v3.conf"
readonly PROXY_ENABLED="/etc/lighttpd/conf-enabled/99-open-sprinkler-v3.conf"
readonly TLS_AVAILABLE="/etc/lighttpd/conf-available/98-open-sprinkler-tls.conf"
readonly TLS_ENABLED="/etc/lighttpd/conf-enabled/98-open-sprinkler-tls.conf"
readonly CERTIFICATE_DIRECTORY="/etc/lighttpd/certs/open-sprinkler"
readonly MKCERT_CA_DIRECTORY="${CONFIGURATION_DIRECTORY}/mkcert-ca"

repository="${PI_SPRINKLER_REPOSITORY:-${DEFAULT_REPOSITORY}}"
source_ref="${PI_SPRINKLER_REF:-${DEFAULT_REF}}"
access_mode=""
tls_hostname=""
tls_ip=""
run_tests=true
start_service=false
valve_power_disconnected=false
full_upgrade=false

usage() {
    cat <<'EOF'
Install Pi Sprinkler Timer 3.0 on Raspberry Pi OS.

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
  --start               Start the controller after validation.
  --valve-power-disconnected
                        Required with --start as a relay safety confirmation.
  -h, --help            Show this help.

The installer never overwrites an existing controller configuration or API
token. It does not enable the GPIO service at boot. Complete relay acceptance
before enabling the service manually.
EOF
}

log() {
    printf '\n==> %s\n' "$*"
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
if [[ "${start_service}" == true && "${valve_power_disconnected}" != true ]]; then
    fail "--start requires --valve-power-disconnected"
fi
command -v apt-get >/dev/null || fail "This installer requires Raspberry Pi OS or Debian"
[[ -r /proc/device-tree/model ]] || fail "Raspberry Pi hardware was not detected"
grep -q "Raspberry Pi" /proc/device-tree/model || fail "Raspberry Pi hardware was not detected"
if systemctl is-active --quiet open-sprinkler-v3.service; then
    fail "Stop open-sprinkler-v3.service before installing or updating"
fi

log "Installing operating-system packages"
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

log "Installing source ref ${source_ref}"
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
if [[ "${run_tests}" == true ]]; then
    "${VIRTUAL_ENVIRONMENT}/bin/pip" install pytest httpx
    "${VIRTUAL_ENVIRONMENT}/bin/pytest" -q "${SOURCE_DIRECTORY}/tests"
fi

log "Creating the restricted service account and configuration"
if ! getent group open-sprinkler >/dev/null; then
    groupadd --system open-sprinkler
fi
if ! getent passwd open-sprinkler >/dev/null; then
    useradd --system --gid open-sprinkler --home-dir /var/lib/open-sprinkler \
        --shell /usr/sbin/nologin open-sprinkler
fi
getent group gpio >/dev/null || fail "Required gpio group does not exist"
usermod --append --groups gpio open-sprinkler
install -d -m 0750 -o root -g open-sprinkler "${CONFIGURATION_DIRECTORY}"
if [[ ! -e "${CONFIGURATION_FILE}" ]]; then
    install -m 0640 -o root -g open-sprinkler \
        "${SOURCE_DIRECTORY}/open-sprinkler-v3.ini.example" \
        "${CONFIGURATION_FILE}"
fi
if [[ ! -s "${TOKEN_FILE}" ]]; then
    install -m 0640 -o root -g open-sprinkler /dev/null "${TOKEN_FILE}"
    systemd-ask-password "Pi Sprinkler Timer API token (at least 32 characters)" \
        >"${TOKEN_FILE}"
fi
chown root:open-sprinkler "${TOKEN_FILE}"
chmod 0640 "${TOKEN_FILE}"
python3 - "${TOKEN_FILE}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
if len(path.read_text(encoding="utf-8").strip()) < 32:
    raise SystemExit(f"API token must contain at least 32 characters: {path}")
PY

log "Installing and validating the systemd service"
install -m 0644 "${SOURCE_DIRECTORY}/systemd/open-sprinkler-v3.service" \
    "${SERVICE_FILE}"
systemctl daemon-reload
systemd-analyze verify "${SERVICE_FILE}"

log "Configuring lighttpd reverse proxy"
install -m 0644 "${SOURCE_DIRECTORY}/lighttpd/99-open-sprinkler-v3.conf" \
    "${PROXY_AVAILABLE}"
enable_lighttpd_configuration "99-open-sprinkler-v3.conf" "${PROXY_ENABLED}"

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
            "${SOURCE_DIRECTORY}/lighttpd/98-open-sprinkler-tls.conf.example" \
            "${TLS_AVAILABLE}"
    fi
    enable_lighttpd_configuration "98-open-sprinkler-tls.conf" "${TLS_ENABLED}"
    openssl x509 -in "${certificate}" -noout -subject -issuer -dates -ext subjectAltName
fi

lighttpd -tt -f /etc/lighttpd/lighttpd.conf
systemctl restart lighttpd
systemctl --no-pager --full status lighttpd

if [[ "${start_service}" == true ]]; then
    log "Starting the controller with valve power confirmed disconnected"
    systemctl start open-sprinkler-v3.service
    systemctl --no-pager --full status open-sprinkler-v3.service
    curl --fail --show-error --max-time 5 http://127.0.0.1:8000/api/v1/health
else
    log "Installation complete; the GPIO service remains stopped and disabled"
fi

printf '\nNext steps:\n'
printf '  1. Review %s and verify every BCM GPIO pin.\n' "${CONFIGURATION_FILE}"
if [[ "${access_mode}" == "https" ]]; then
    printf '  2. Trust the public CA at %s/rootCA.pem on client devices.\n' "${MKCERT_CA_DIRECTORY}"
else
    printf '  2. Use a temporary token only on a trusted isolated LAN.\n'
fi
printf '  3. Keep valve power disconnected and run the relay acceptance checklist.\n'
printf '  4. After acceptance: sudo systemctl enable --now open-sprinkler-v3.service\n'
