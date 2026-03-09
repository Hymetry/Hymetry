#!/bin/sh
set -eu

# Function to wait for Postgres
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
        # Heroku provides DATABASE_URL automatically
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        conn.close()
        print("Postgres is ready.")
        sys.exit(0)
    except Exception as e:
        last_err = e
        time.sleep(2)

raise SystemExit(f"Postgres not ready after timeout. Last error: {last_err}")
PY
}

# Only wait if not explicitly skipped
if [ "${SKIP_DB_WAIT:-0}" != "1" ]; then
  wait_for_postgres
fi

# Note: We NO LONGER run migrate or loaddata here.
# Those are handled by the 'release' command in heroku.yml.

echo "Starting Hymetry process: $@"
exec "$@"