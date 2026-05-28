#!/bin/bash
set -e

cat <<'EOF'
VPS Traffic Panel uninstall helper

For safety, this script does not remove files automatically.
Run these commands manually if you want to uninstall:

1. Stop and disable the service:
   systemctl stop vps-traffic-panel
   systemctl disable vps-traffic-panel

2. Remove or archive the service file:
   mv /etc/systemd/system/vps-traffic-panel.service /etc/systemd/system/vps-traffic-panel.service.disabled
   systemctl daemon-reload

3. Archive the installation directory if needed:
   mv /opt/vps-traffic-panel /opt/vps-traffic-panel.uninstalled

EOF
