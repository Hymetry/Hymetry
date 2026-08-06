import os
import tempfile
import time
from pathlib import Path

import psycopg2

from django.core.management import BaseCommand, call_command
from django.db import IntegrityError
from django.utils import timezone


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
        installation = None
        if os.environ.get("BOOTSTRAP_SKIP_DB", "0") != "1":
            self._wait_for_db_and_optionally_create()

        if os.environ.get("BOOTSTRAP_SKIP_MIGRATE", "0") != "1":
            call_command(
                "migrate",
                interactive=False,
                verbosity=1,
                run_syncdb=os.environ.get("BOOTSTRAP_RUN_SYNCDB", "1") == "1",
            )

        if os.environ.get("BOOTSTRAP_SKIP_MIGRATE", "0") != "1":
            from apps.core.models import InstallationState

            installation, _ = InstallationState.objects.get_or_create(pk=1)

        if os.environ.get("BOOTSTRAP_SKIP_COLLECTSTATIC", "0") != "1":
            call_command("collectstatic", interactive=False, verbosity=1, clear=False)

        fixtures_enabled = os.environ.get("BOOTSTRAP_LOAD_FIXTURES", "1") == "1"
        force_fixtures = os.environ.get("BOOTSTRAP_FORCE_FIXTURES", "0") == "1"
        seed_required = installation is not None and installation.seed_initialized_at is None
        if fixtures_enabled and (seed_required or force_fixtures):
            self._load_seed_fixtures()
            self._ensure_bootstrap_prompt_defaults()
            if installation is not None:
                installation.seed_initialized_at = timezone.now()
                installation.save(update_fields=["seed_initialized_at", "updated_at"])
        elif fixtures_enabled:
            self.stdout.write("Seed fixtures already initialized; preserving database configuration.")

        if os.environ.get("BOOTSTRAP_CONFIGURE_PERIODIC_TASKS", "1") == "1":
            self._configure_periodic_tasks()

    def _load_seed_fixtures(self) -> None:
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

    def _ensure_bootstrap_prompt_defaults(self) -> None:
        from apps.tracker.models import TitlePrompt

        for prompt in TitlePrompt.objects.all():
            update_fields = []
            if not prompt.bootstrap_page_naming_prompt:
                prompt.bootstrap_page_naming_prompt = prompt.hourly_unstable_prompt
                update_fields.append("bootstrap_page_naming_prompt")
            if not prompt.bootstrap_page_naming_openai_model:
                prompt.bootstrap_page_naming_openai_model = prompt.hourly_unstable_openai_model
                update_fields.append("bootstrap_page_naming_openai_model")
            if update_fields:
                prompt.save(update_fields=[*update_fields, "updated_at"])

    def _configure_periodic_tasks(self) -> None:
        for command_name in (
            "schedule_tracker_maintenance_tasks",
            "schedule_page_naming_tasks",
            "schedule_pages_analytics_tasks",
            "schedule_recording_visits_cleanup",
            "schedule_project_lifecycle_tasks",
        ):
            call_command(command_name, mode="real")

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

