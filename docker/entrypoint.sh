#!/bin/sh
set -eu

# 1. Wait for Postgres (Condensed & Robust)
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

import django  # noqa: E402
django.setup()

from django.core.management import call_command  # noqa: E402

# List of fixtures to load
fixtures = [
    Path("/app/docker/fixtures/ai.json"),
    Path("/app/docker/fixtures/celery_beat.json"),
]

for fixture_path in fixtures:
    if not fixture_path.exists():
        print(f"Fixture not found at {fixture_path}; skipping.")
        continue

    print(f"Loading fixture from {fixture_path}...")
    call_command("loaddata", str(fixture_path))

    # Special normalization for celery_beat
    if fixture_path.name == "celery_beat.json":
        try:
            from django_celery_beat.models import PeriodicTask
            update_fields = {}
            if "last_run_at" in [f.name for f in PeriodicTask._meta.fields]:
                update_fields["last_run_at"] = None
            if "total_run_count" in [f.name for f in PeriodicTask._meta.fields]:
                update_fields["total_run_count"] = 0
            if update_fields:
                PeriodicTask.objects.update(**update_fields)
        except Exception as e:
            print(f"Celery-beat post-load normalization skipped: {e}")

print("All fixtures loaded.")
sys.exit(1)
PY
echo "Postgres is ready."
fi

# 2. Run Release Tasks
# Note: These are now here instead of heroku.yml to ensure
# they run with the full environment and DB connection.
echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

# 3. Start Process
echo "Starting Hymetry process: $@"
exec "$@"