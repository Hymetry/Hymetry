#!/bin/sh
set -eu

# 1. Wait for Postgres and Load Data
if [ "${SKIP_DB_WAIT:-0}" != "1" ]; then
  echo "Waiting for database and loading fixtures..."
  python - <<'PY'
import os, sys, time, psycopg2
from pathlib import Path

# Connect to DB
deadline = time.time() + int(os.environ.get("DB_WAIT_SECONDS", "60"))
connected = False
while time.time() < deadline:
    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        conn.close()
        connected = True
        break
    except Exception:
        time.sleep(2)

if not connected:
    print("Postgres not ready after timeout.")
    sys.exit(1)

# Django Setup
import django
django.setup()
from django.core.management import call_command

fixtures = [
    Path("/app/docker/fixtures/ai.json"),
    Path("/app/docker/fixtures/celery_beat.json"),
]

for fixture_path in fixtures:
    if fixture_path.exists():
        print(f"Loading fixture: {fixture_path}")
        call_command("loaddata", str(fixture_path))

        if fixture_path.name == "celery_beat.json":
            try:
                from django_celery_beat.models import PeriodicTask
                PeriodicTask.objects.update(last_run_at=None, total_run_count=0)
            except Exception as e:
                print(f"Celery-beat normalization skipped: {e}")

sys.exit(0) # Success!
PY
fi

# 2. Run Release Tasks
echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

# 3. Start Process
echo "Starting Hymetry process: $@"
exec "$@"