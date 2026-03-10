#!/bin/sh
set -eu

# 1. Wait for Postgres (Just the connection check)
if [ "${SKIP_DB_WAIT:-0}" != "1" ]; then
  echo "Waiting for database..."
  python - <<'PY'
import os, sys, time, psycopg2
deadline = time.time() + int(os.environ.get("DB_WAIT_SECONDS", "60"))
while time.time() < deadline:
    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        conn.close()
        sys.exit(0)
    except Exception:
        time.sleep(2)
sys.exit(1)
PY
fi

# 2. Database Setup (Migrations MUST come before Fixtures)
# We only run this if the command is starting the web server to avoid race conditions
case "$*" in
  *"gunicorn"*|*"runserver"*)
    echo "Running migrations..."
    python manage.py migrate --noinput

    echo "Loading fixtures..."
    python - <<'PY'
import django
import os, sys
from pathlib import Path
from django.core.management import call_command

django.setup()

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
PY
    ;;
  *)
    echo "Skipping migrations/fixtures for non-web process..."
    ;;
esac

echo "Collecting static files..."
python manage.py collectstatic --noinput

# 3. Start Process
echo "Starting Hymetry process: $@"
exec "$@"