import os
import tempfile
import time
from pathlib import Path

import psycopg2
from psycopg2 import sql

from django.core.management import BaseCommand, call_command
from django.db import IntegrityError


class Command(BaseCommand):
    help = "Initialize the app (create DB if needed, migrate, collectstatic, load fixtures)."

    def _pg_env(self):
        return {
            "host": os.environ.get("POSTGRES_HOST", "db"),
            "port": int(os.environ.get("POSTGRES_PORT", "5432")),
            "name": os.environ.get("POSTGRES_DB"),
            "user": os.environ.get("POSTGRES_USER"),
            "password": os.environ.get("POSTGRES_PASSWORD"),
            "admin_db": os.environ.get("POSTGRES_ADMIN_DB", "postgres"),
            "wait_seconds": int(os.environ.get("DB_WAIT_SECONDS", "60")),
            "create_db": os.environ.get("BOOTSTRAP_CREATE_DB", "1") == "1",
        }

    def _wait_for_db_and_optionally_create(self):
        env = self._pg_env()
        missing = [k for k in ("name", "user", "password") if not env.get(k)]
        if missing:
            raise SystemExit(f"Missing required env vars for DB: {', '.join(missing)}")

        deadline = time.time() + env["wait_seconds"]
        last_err = None

        while time.time() < deadline:
            try:
                conn = psycopg2.connect(
                    dbname=env["admin_db"],
                    user=env["user"],
                    password=env["password"],
                    host=env["host"],
                    port=env["port"],
                )
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (env["name"],))
                    exists = cur.fetchone() is not None
                    if exists:
                        self.stdout.write(self.style.SUCCESS(f"Database {env['name']} exists."))
                        conn.close()
                        return

                    if not env["create_db"]:
                        conn.close()
                        raise SystemExit(
                            f"Database {env['name']} does not exist. "
                            f"Either create it, or set BOOTSTRAP_CREATE_DB=1."
                        )

                    cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(env["name"])))
                    self.stdout.write(self.style.SUCCESS(f"Created database {env['name']}."))
                conn.close()
                return
            except Exception as e:
                last_err = e
                time.sleep(1)

        raise SystemExit(f"Database not ready after timeout. Last error: {last_err}")

    def handle(self, *args, **options):
        if os.environ.get("BOOTSTRAP_SKIP_DB", "0") != "1":
            self._wait_for_db_and_optionally_create()

        if os.environ.get("BOOTSTRAP_SKIP_MIGRATE", "0") != "1":
            run_syncdb = os.environ.get("BOOTSTRAP_RUN_SYNCDB", "1") == "1"
            call_command("migrate", interactive=False, verbosity=1, run_syncdb=run_syncdb)

        if os.environ.get("BOOTSTRAP_SKIP_COLLECTSTATIC", "0") != "1":
            call_command("collectstatic", interactive=False, verbosity=1, clear=False)

        if os.environ.get("BOOTSTRAP_LOAD_FIXTURES", "1") != "1":
            return

        fixtures_dir = self._resolve_fixtures_dir()
        if not fixtures_dir.exists():
            self.stdout.write(f"Fixtures dir {fixtures_dir} not found; skipping.")
            return

        fixture_paths = sorted(fixtures_dir.glob("*.json"))
        if not fixture_paths:
            self.stdout.write("No JSON fixtures found; skipping.")
            return

        for fixture_path in fixture_paths:
            self._load_fixture_path(fixture_path)

    def _resolve_fixtures_dir(self) -> Path:
        override = os.environ.get("FIXTURES_DIR")
        if override:
            return Path(override)

        for candidate in (Path("fixtures"), Path("docker/fixtures")):
            if candidate.exists():
                return candidate

        return Path("fixtures")

    def _load_fixture_path(self, fixture_path: Path) -> None:
        self.stdout.write(f"Loading fixture {fixture_path}...")

        raw = fixture_path.read_bytes()
        load_path = fixture_path

        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            decoded = None
            for enc in ("utf-16", "utf-16-le", "utf-16-be"):
                try:
                    decoded = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            if decoded is None:
                raise SystemExit(f"Fixture {fixture_path} is not UTF-8/UTF-16 readable.")

            tmp = tempfile.NamedTemporaryFile(
                "w",
                delete=False,
                suffix=".json",
                encoding="utf-8",
                newline="\n",
            )
            try:
                tmp.write(decoded)
                tmp.flush()
            finally:
                tmp.close()
            load_path = Path(tmp.name)

        try:
            call_command("loaddata", str(load_path))
            self.stdout.write(self.style.SUCCESS(f"Loaded fixture {fixture_path}."))
        except IntegrityError:
            self.stdout.write(f"Fixture {fixture_path} looks already applied; skipping.")
        finally:
            if load_path != fixture_path:
                try:
                    load_path.unlink(missing_ok=True)
                except Exception:
                    pass

