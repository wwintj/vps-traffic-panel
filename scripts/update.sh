#!/bin/bash
set -e

echo "Updating VPS Traffic Panel..."
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$INSTALL_DIR"

mkdir -p backups
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
[ -f .env ] && cp .env "backups/.env.$TIMESTAMP.bak"
[ -f data.db ] && cp data.db "backups/data.db.$TIMESTAMP.bak"

if [ -d .git ]; then
    git pull origin main
else
    echo "This directory is not a Git repository. Please update files manually."
fi

if [ -d venv ]; then
    . venv/bin/activate
    pip install -r requirements.txt
fi

echo "Update files completed. Please restart vps-traffic-panel service if needed."
