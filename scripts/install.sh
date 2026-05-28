#!/bin/bash
set -e

GREEN="\033[32m"
RED="\033[31m"
YELLOW="\033[33m"
RESET="\033[0m"

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

echo -e "${YELLOW}Installing dependencies...${RESET}"
apt-get update
apt-get install -y python3 python3-venv python3-pip python3-dev gcc sqlite3 curl rsync git iproute2

echo -e "${YELLOW}Copying project files...${RESET}"
mkdir -p "$INSTALL_DIR"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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
EOF
chmod 600 .env

echo -e "${YELLOW}Configuring systemd service...${RESET}"
cat > /etc/systemd/system/vps-traffic-panel.service <<EOF
[Unit]
Description=VPS Traffic Panel
After=network.target

[Service]
User=root
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$INSTALL_DIR/.env
ExecStart=$INSTALL_DIR/venv/bin/uvicorn app.main:app --host \$HOST --port \$PORT
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable vps-traffic-panel
systemctl restart vps-traffic-panel

echo -e "${GREEN}====================================${RESET}"
echo -e "${GREEN}Installation Successful!${RESET}"
echo -e "Access your panel at : http://$HOST:$PORT"
echo -e "Check service status : systemctl status vps-traffic-panel"
echo -e "View running logs    : journalctl -u vps-traffic-panel -f"
echo -e "${GREEN}====================================${RESET}"
