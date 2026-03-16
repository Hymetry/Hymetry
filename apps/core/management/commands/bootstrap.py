import os
import tempfile
import time
from pathlib import Path

import psycopg2

from django.core.management import BaseCommand, call_command
from django.db import IntegrityError


class Command(BaseCommand):
    help = "Initialize the app (create DB if needed, migrate, collectstatic, load fixtures)."

    def _wait_for_db_and_optionally_create(self):
        wait_seconds = int(os.environ.get("DB_WAIT_SECONDS", "60"))
        database_url = os.environ.get("DATABASE_URL")

        if not database_url:
            raise SystemExit("DATABASE_URL is required for bootstrap.")

        deadline = time.time() + wait_seconds
        last_err = None
        while time.time() < deadline:
            try:
                conn = psycopg2.connect(database_url)
                conn.close()
                self.stdout.write(self.style.SUCCESS("Database is reachable via DATABASE_URL."))
                return
            except Exception as e:
                last_err = e
                time.sleep(1)

        raise SystemExit(f"Database not ready after timeout. Last error: {last_err}")

    def handle(self, *_args, **_options):
        if os.environ.get("BOOTSTRAP_SKIP_DB", "0") != "1":
            self._wait_for_db_and_optionally_create()

        if os.environ.get("BOOTSTRAP_SKIP_MIGRATE", "0") != "1":
            call_command(
                "migrate",
                interactive=False,
                verbosity=1,
                run_syncdb=os.environ.get("BOOTSTRAP_RUN_SYNCDB", "1") == "1",
            )

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

