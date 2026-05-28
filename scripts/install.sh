#!/bin/bash
set -e

GREEN="\033[32m"
RED="\033[31m"
YELLOW="\033[33m"
RESET="\033[0m"
SERVICE_NAME="vps-traffic-panel"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cleanup_previous_install() {
    local install_dir="$1"
    local timestamp
    timestamp=$(date +"%Y%m%d_%H%M%S")
    local old_dirs=()

    echo -e "${YELLOW}Checking for previous VPS Traffic Panel installation...${RESET}"

    if [ -f "$SERVICE_FILE" ]; then
        local service_dir
        service_dir=$(awk -F= '/^WorkingDirectory=/{print $2; exit}' "$SERVICE_FILE" || true)
        [ -n "$service_dir" ] && old_dirs+=("$service_dir")

        echo -e "${YELLOW}Previous systemd service found. Stopping and disabling it...${RESET}"
        systemctl stop "$SERVICE_NAME" 2>/dev/null || true
        systemctl disable "$SERVICE_NAME" 2>/dev/null || true
        rm -f "$SERVICE_FILE"
        systemctl daemon-reload
    fi

    old_dirs+=("$install_dir")

    local dir
    local handled=" "
    for dir in "${old_dirs[@]}"; do
        [ -z "$dir" ] && continue
        case "$handled" in
            *" $dir "*) continue ;;
        esac
        handled="$handled$dir "

        if [ -d "$dir" ]; then
            if [ "$(readlink -f "$dir")" = "$(readlink -f "$PROJECT_ROOT")" ]; then
                echo -e "${YELLOW}Install directory is the current source directory; keeping source files in place.${RESET}"
                continue
            fi

            local backup_dir="${dir}.old.${timestamp}"
            echo -e "${YELLOW}Moving previous install directory to: $backup_dir${RESET}"
            mv "$dir" "$backup_dir"
        fi
    done
}

detect_ssl_certificates() {
    SSL_ENABLED=0
    SSL_CERTFILE=""
    SSL_KEYFILE=""

    local cert_dirs=()
    if [ -d /etc/letsencrypt/live ]; then
        while IFS= read -r cert_dir; do
            [ -f "$cert_dir/fullchain.pem" ] && [ -f "$cert_dir/privkey.pem" ] && cert_dirs+=("$cert_dir")
        done < <(find /etc/letsencrypt/live -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
    fi

    if [ "${#cert_dirs[@]}" -eq 0 ]; then
        echo -e "${YELLOW}No Let's Encrypt SSL certificate found. The panel will run over HTTP.${RESET}"
        return
    fi

    echo -e "${GREEN}Detected existing SSL certificate(s):${RESET}"
    local i
    for i in "${!cert_dirs[@]}"; do
        echo "  $((i + 1))) ${cert_dirs[$i]}"
    done

    read -p "Use one of these certificates for HTTPS? [y/N]: " use_ssl
    if [[ ! "$use_ssl" =~ ^[Yy]$ ]]; then
        return
    fi

    local choice
    while true; do
        read -p "Select certificate number [1]: " choice
        choice=${choice:-1}
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#cert_dirs[@]}" ]; then
            local selected="${cert_dirs[$((choice - 1))]}"
            SSL_ENABLED=1
            SSL_CERTFILE="$selected/fullchain.pem"
            SSL_KEYFILE="$selected/privkey.pem"
            break
        fi
        echo -e "${RED}Error: Please choose a valid certificate number.${RESET}"
    done
}

if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Error: Please run as root.${RESET}"
  exit 1
fi

if ! grep -qE "Ubuntu 22.04|Ubuntu 24.04|Debian GNU/Linux 12" /etc/os-release; then
  echo -e "${YELLOW}Warning: This script is optimized for Ubuntu 22.04/24.04 and Debian 12.${RESET}"
  read -p "Your current OS may not be fully supported. Continue anyway? [y/N]: " proceed
  if [[ ! "$proceed" =~ ^[Yy]$ ]]; then
      echo -e "${RED}Installation aborted.${RESET}"
      exit 1
  fi
fi

if ! command -v ss >/dev/null 2>&1; then
    echo -e "${YELLOW}Installing basic network tools for port detection...${RESET}"
    apt-get update -qq && apt-get install -y iproute2 -qq >/dev/null
fi

echo -e "${GREEN}=== VPS Traffic Panel Installer ===${RESET}"

read -p "Install directory [/opt/vps-traffic-panel]: " INSTALL_DIR
INSTALL_DIR=${INSTALL_DIR:-/opt/vps-traffic-panel}

cleanup_previous_install "$INSTALL_DIR"

read -p "Web Bind Address [127.0.0.1]: " HOST
HOST=${HOST:-127.0.0.1}

if [ "$HOST" == "0.0.0.0" ]; then
    echo -e "${RED}WARNING: You are binding to 0.0.0.0. Exposing the panel directly to the internet carries risks. Ensure your password is very strong!${RESET}"
    sleep 2
fi

while true; do
    read -p "Web Port [8088]: " PORT
    PORT=${PORT:-8088}
    
    if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
        echo -e "${RED}Error: Port must be a number between 1 and 65535.${RESET}"
        continue
    fi

    if ss -tuln | awk '{print $5}' | grep -qE ":$PORT$"; then
        echo -e "${RED}Error: Port $PORT is already in use. Please choose another port.${RESET}"
    else
        break
    fi
done

read -p "Login Username [admin]: " AUTH_USERNAME
AUTH_USERNAME=${AUTH_USERNAME:-admin}

while true; do
    read -s -p "Login Password: " AUTH_PASSWORD
    echo ""
    
    if [[ -z "$AUTH_PASSWORD" || "$AUTH_PASSWORD" == "admin" || "$AUTH_PASSWORD" == "password" || "$AUTH_PASSWORD" == "123456" ]]; then
        echo -e "${RED}Error: Password cannot be empty or a weak default (admin/password/123456). Please enter a secure password.${RESET}"
        continue
    fi
    
    if [[ ! "$AUTH_PASSWORD" =~ ^[a-zA-Z0-9@_\.\!\%\-]+$ ]]; then
        echo -e "${RED}Error: Password contains invalid characters. Only alphanumeric and @ _ - . ! % are allowed.${RESET}"
        continue
    fi
    
    break
done

read -p "Network Interface (Leave blank for auto-detect): " INTERFACE

detect_ssl_certificates

echo -e "${YELLOW}Installing dependencies...${RESET}"
apt-get update
apt-get install -y python3 python3-venv python3-pip python3-dev gcc sqlite3 curl rsync git iproute2

echo -e "${YELLOW}Copying project files...${RESET}"
mkdir -p "$INSTALL_DIR"

rsync -av --exclude={'venv','__pycache__','*.db','*.db-shm','*.db-wal','.env','.env.example','backups','*.bak'} "$PROJECT_ROOT/" "$INSTALL_DIR/"

cd "$INSTALL_DIR"

echo -e "${YELLOW}Setting up Python Virtual Environment...${RESET}"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo -e "${YELLOW}Generating .env file...${RESET}"
cat > .env <<EOF
HOST=$HOST
PORT=$PORT
AUTH_USERNAME=$AUTH_USERNAME
AUTH_PASSWORD=$AUTH_PASSWORD
INTERFACE=$INTERFACE
SSL_ENABLED=$SSL_ENABLED
SSL_CERTFILE=$SSL_CERTFILE
SSL_KEYFILE=$SSL_KEYFILE
EOF
chmod 600 .env

echo -e "${YELLOW}Configuring systemd service...${RESET}"
if [ "$SSL_ENABLED" -eq 1 ]; then
    EXEC_START="$INSTALL_DIR/venv/bin/uvicorn app.main:app --host \$HOST --port \$PORT --ssl-certfile \$SSL_CERTFILE --ssl-keyfile \$SSL_KEYFILE"
else
    EXEC_START="$INSTALL_DIR/venv/bin/uvicorn app.main:app --host \$HOST --port \$PORT"
fi

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=VPS Traffic Panel
After=network.target

[Service]
User=root
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$INSTALL_DIR/.env
ExecStart=$EXEC_START
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

SCHEME="http"
[ "$SSL_ENABLED" -eq 1 ] && SCHEME="https"

echo -e "${GREEN}====================================${RESET}"
echo -e "${GREEN}Installation Successful!${RESET}"
echo -e "Access your panel at : $SCHEME://$HOST:$PORT"
echo -e "Check service status : systemctl status $SERVICE_NAME"
echo -e "View running logs    : journalctl -u $SERVICE_NAME -f"
echo -e "${GREEN}====================================${RESET}"
