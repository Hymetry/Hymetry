#!/bin/bash
set -e

TOKEN="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"
PROJECT_DIR="/opt/productpathpro"
VENV_DIR="$PROJECT_DIR/venv"
LOG_FILE="/var/log/github_deploy.log"

echo ">>> SCRIPT STARTED $(date)" >> "$LOG_FILE" 2>&1

cd "$PROJECT_DIR" || { echo "Failed to cd $PROJECT_DIR" >> "$LOG_FILE" 2>&1; exit 1; }

echo ">>> Resetting local changes" >> "$LOG_FILE" 2>&1
git reset --hard >> "$LOG_FILE" 2>&1
git clean -fd >> "$LOG_FILE" 2>&1

echo ">>> Pulling latest changes from GitHub" >> "$LOG_FILE" 2>&1
git pull https://$TOKEN@github.com/ArtemSyzonenko/productpathpro.git main >> "$LOG_FILE" 2>&1

echo ">>> Activating virtual environment" >> "$LOG_FILE" 2>&1
source "$VENV_DIR/bin/activate"

echo ">>> Applying migrations" >> "$LOG_FILE" 2>&1
python manage.py migrate --noinput --settings=config.settings.prod >> "$LOG_FILE" 2>&1

echo ">>> Collecting static files" >> "$LOG_FILE" 2>&1
python manage.py collectstatic --noinput --settings=config.settings.prod >> "$LOG_FILE"

sudo systemctl restart gunicorn
echo ">>> Finished"