#!/bin/bash
set -e

SERVICE_NAME="vps-traffic-panel"
INSTALL_DIR="${INSTALL_DIR:-/opt/vps-traffic-panel}"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ -z "$INSTALL_DIR" || "$INSTALL_DIR" == "/" || "$INSTALL_DIR" == "/opt" ]]; then
    echo "Refusing to remove unsafe install directory: $INSTALL_DIR"
    exit 1
fi

echo "=== VPS Traffic Panel Uninstaller ==="

if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
    echo "Stopping and disabling service..."
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
fi

if [[ -f "$SERVICE_FILE" ]]; then
    echo "Removing systemd service file..."
    rm -f "$SERVICE_FILE"
fi

systemctl daemon-reload

if [[ -d "$INSTALL_DIR" ]]; then
    echo "Removing install directory: $INSTALL_DIR"
    cd /
    rm -rf "$INSTALL_DIR"
fi

echo "Uninstall completed."
