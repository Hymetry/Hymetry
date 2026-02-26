#!/bin/sh
set -eu

wait_for_postgres() {
  python - <<'PY'
import os
import sys
import time
import psycopg2

host = os.environ.get("POSTGRES_HOST", "db")
port = int(os.environ.get("POSTGRES_PORT", "5432"))
name = os.environ.get("POSTGRES_DB")
user = os.environ.get("POSTGRES_USER")
password = os.environ.get("POSTGRES_PASSWORD")

deadline = time.time() + int(os.environ.get("DB_WAIT_SECONDS", "60"))
last_err = None

while time.time() < deadline:
    try:
        conn = psycopg2.connect(
            dbname=name,
            user=user,
            password=password,
            host=host,
            port=port,
        )
        conn.close()
        print("Postgres is ready.")
        sys.exit(0)
    except Exception as e:
        last_err = e
        time.sleep(1)

raise SystemExit(f"Postgres not ready after timeout. Last error: {last_err}")
PY
}

if [ "${SKIP_DB_WAIT:-0}" != "1" ]; then
  wait_for_postgres
fi

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput --settings="${DJANGO_SETTINGS_MODULE:-config.settings.prod_cloud}"
fi

if [ "${LOAD_CELERY_BEAT_FIXTURE:-0}" = "1" ]; then
  python - <<'PY'
import os
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.environ.get("DJANGO_SETTINGS_MODULE", "config.settings.prod_cloud"))

import django  # noqa: E402

django.setup()

from django.core.management import call_command  # noqa: E402

fixture_path = Path(os.environ.get("CELERY_BEAT_FIXTURE_PATH", "/app/fixtures/celery_beat.json"))
if not fixture_path.exists():
    print(f"Celery-beat fixture not found at {fixture_path}; skipping.")
    raise SystemExit(0)

try:
    from django_celery_beat.models import PeriodicTask  # noqa: E402
except Exception as e:
    print(f"django_celery_beat not available ({e}); skipping.")
    raise SystemExit(0)

if PeriodicTask.objects.exists():
    print("Celery-beat tasks already exist; skipping fixture load.")
    raise SystemExit(0)

print(f"Loading celery-beat fixture from {fixture_path}...")
call_command("loaddata", str(fixture_path))

try:
    update_fields = {}
    if "last_run_at" in [f.name for f in PeriodicTask._meta.fields]:
        update_fields["last_run_at"] = None
    if "total_run_count" in [f.name for f in PeriodicTask._meta.fields]:
        update_fields["total_run_count"] = 0
    if update_fields:
        PeriodicTask.objects.update(**update_fields)
except Exception as e:
    print(f"Post-load normalization skipped: {e}")

print("Celery-beat fixture load complete.")
PY
fi

if [ "${RUN_COLLECTSTATIC:-1}" = "1" ]; then
  python manage.py collectstatic --noinput --settings="${DJANGO_SETTINGS_MODULE:-config.settings.prod_cloud}"
fi

exec "$@"

