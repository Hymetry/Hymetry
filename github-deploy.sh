#!/bin/bash
set -e

PROJECT_DIR="/opt/productpathpro"
VENV_DIR="$PROJECT_DIR/venv"
LOG_FILE="/var/log/github_deploy.log"

echo ">>> SCRIPT STARTED $(date)" >> "$LOG_FILE" 2>&1

cd "$PROJECT_DIR" || { echo "Failed to cd $PROJECT_DIR" >> "$LOG_FILE" 2>&1; exit 1; }

# Load GITHUB_DEPLOY_TOKEN and DJANGO_SETTINGS_MODULE from .env (don't source whole file - .env may have Django-style or spaces)
if [ -f "$PROJECT_DIR/.env" ]; then
  GITHUB_DEPLOY_TOKEN=$(grep -E '^GITHUB_DEPLOY_TOKEN=' "$PROJECT_DIR/.env" | cut -d= -f2- | head -1)
  GITHUB_DEPLOY_TOKEN=$(echo "$GITHUB_DEPLOY_TOKEN" | sed -e 's/^["'\'']//' -e 's/["'\'']$//')
  DJANGO_SETTINGS_MODULE=$(grep -E '^DJANGO_SETTINGS_MODULE=' "$PROJECT_DIR/.env" | cut -d= -f2- | head -1)
  DJANGO_SETTINGS_MODULE=$(echo "$DJANGO_SETTINGS_MODULE" | sed -e 's/^["'\'']//' -e 's/["'\'']$//')
fi
DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE:-config.settings.prod_cloud}
if [ -z "${GITHUB_DEPLOY_TOKEN:-}" ]; then
  echo ">>> ERROR: GITHUB_DEPLOY_TOKEN not set (add to $PROJECT_DIR/.env)" >> "$LOG_FILE" 2>&1
  exit 1
fi

echo ">>> Resetting local changes" >> "$LOG_FILE" 2>&1
git reset --hard >> "$LOG_FILE" 2>&1
git clean -fd >> "$LOG_FILE" 2>&1

echo ">>> Pulling latest changes from GitHub" >> "$LOG_FILE" 2>&1
git pull https://$GITHUB_DEPLOY_TOKEN@github.com/ArtemSyzonenko/productpathpro.git main >> "$LOG_FILE" 2>&1

echo ">>> Activating virtual environment" >> "$LOG_FILE" 2>&1
source "$VENV_DIR/bin/activate"

echo ">>> Applying migrations" >> "$LOG_FILE" 2>&1
python manage.py migrate --noinput --settings="$DJANGO_SETTINGS_MODULE" >> "$LOG_FILE" 2>&1

echo ">>> Generate output css" >> "$LOG_FILE" 2>&1
bash frontend/tailwind/run.sh >> "$LOG_FILE" 2>&1

echo ">>> Collecting static files" >> "$LOG_FILE" 2>&1
python manage.py collectstatic --noinput --settings="$DJANGO_SETTINGS_MODULE" >> "$LOG_FILE"

sudo systemctl restart gunicorn
sudo systemctl restart celery
sudo systemctl restart celery-beat
echo ">>> Finished"