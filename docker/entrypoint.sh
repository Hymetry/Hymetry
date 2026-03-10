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