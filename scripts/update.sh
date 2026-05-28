#!/bin/bash
set -e

GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"
SERVICE_NAME="vps-traffic-panel"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Error: Please run as root.${RESET}"
  exit 1
fi

echo -e "${GREEN}=== VPS Traffic Panel Updater ===${RESET}"

INSTALL_DIR="/opt/vps-traffic-panel"
if [ -f "$SERVICE_FILE" ]; then
    service_dir=$(awk -F= '/^WorkingDirectory=/{print $2; exit}' "$SERVICE_FILE" || true)
    [ -n "$service_dir" ] && INSTALL_DIR="$service_dir"
fi

if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${RED}Error: Install directory not found: $INSTALL_DIR${RESET}"
    echo "Run sudo ./scripts/install.sh first."
    exit 1
fi

mkdir -p "$INSTALL_DIR/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
[ -f "$INSTALL_DIR/.env" ] && cp "$INSTALL_DIR/.env" "$INSTALL_DIR/backups/.env.$TIMESTAMP.bak"
[ -f "$INSTALL_DIR/data.db" ] && cp "$INSTALL_DIR/data.db" "$INSTALL_DIR/backups/data.db.$TIMESTAMP.bak"

if [ -d "$SOURCE_DIR/.git" ]; then
    echo -e "${YELLOW}Pulling latest source from GitHub...${RESET}"
    git -C "$SOURCE_DIR" fetch origin
    git -C "$SOURCE_DIR" reset --hard origin/main
else
    echo -e "${YELLOW}Source directory is not a Git repository. Using local files only.${RESET}"
fi

echo -e "${YELLOW}Syncing application files...${RESET}"
rsync -av --delete \
    --exclude={'.git','venv','__pycache__','*.db','*.db-shm','*.db-wal','.env','.env.example','backups','*.bak'} \
    "$SOURCE_DIR/" "$INSTALL_DIR/"

cd "$INSTALL_DIR"
if [ ! -d venv ]; then
    python3 -m venv venv
fi

echo -e "${YELLOW}Updating Python dependencies...${RESET}"
. venv/bin/activate
pip install -r requirements.txt

echo -e "${YELLOW}Restarting service...${RESET}"
systemctl daemon-reload
systemctl restart "$SERVICE_NAME"

echo -e "${GREEN}Update completed.${RESET}"
echo -e "Install directory : $INSTALL_DIR"
echo -e "Service status   : systemctl status $SERVICE_NAME"
echo -e "Logs             : journalctl -u $SERVICE_NAME -f"
