#!/bin/sh
set -eu


wait_for_postgres() {
  python - <<'PY'
import os
import sys
import time
import psycopg2

print("==== ENV DUMP START ====")
for k, v in os.environ.items():
    print(f"{k}={repr(v)}")
print("==== ENV DUMP END ====")


deadline = time.time() + int(os.environ.get("DB_WAIT_SECONDS", "60"))
last_err = None

while time.time() < deadline:
    try:
        conn = psycopg2.connect(
            os.environ["DATABASE_URL"],
            sslmode="require",
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

python manage.py collectstatic --noinput --settings="${DJANGO_SETTINGS_MODULE:-config.settings.prod}"
# Run migrations
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput --settings="${DJANGO_SETTINGS_MODULE:-config.settings.prod}"
fi

# Load Django fixtures
python - <<'PY'
import os
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.environ.get("DJANGO_SETTINGS_MODULE", "config.settings.prod"))

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
PY

# Execute original CMD
exec "$@"