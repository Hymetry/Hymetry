import csv
import json
import uuid
from datetime import timezone as dt_timezone
from pathlib import Path

import re2
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.tracker.models import (
    AnalyticsEvent,
    AnalyticsSession,
    ProjectPageNamingRun,
    ProjectPageNamingRunMode,
    ProjectPageRule,
)
from apps.tracker.page_naming import ensure_project_first_event_at, normalize_page_url_key
from apps.tracker.testing.replay_runtime import resolve_project

EVENT_COLUMNS = [
    "id",
    "event_type",
    "timestamp",
    "visitor_guid",
    "user_id",
    "company_id",
    "user_traits",
    "company_traits",
    "element_key",
    "page",
    "page_normalized",
    "page_name",
    "origin_page_title",
    "session_id",
    "page_rule_id",
]
OPTIONAL_EVENT_COLUMNS = [
    "product_area",
]

SESSION_COLUMNS = [
    "session_id",
    "visitor_guid",
    "user_id",
    "company_id",
    "start_time",
    "last_activity",
    "ended_at",
    "project_id",
]

PAGE_RULE_COLUMNS = [
    "page_rule_id",
    "pattern",
    "page_normalized",
    "page_name",
    "priority",
]
OPTIONAL_PAGE_RULE_COLUMNS = [
    "product_area",
]

ALLOWED_EVENT_TYPES = {
    "scroll",
    "mouse_move",
    "click",
    "key_press",
    "touch_move",
}


def _regex_fullmatch(compiled_pattern, value):
    if hasattr(compiled_pattern, "fullmatch"):
        return compiled_pattern.fullmatch(value)

    match = compiled_pattern.match(value)
    if not match:
        return None
    return match if match.group(0) == value else None


def build_project_scoped_uuid(project_id, entity_type, source_uuid):
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"hymetry-synthetic:{project_id}:{entity_type}:{source_uuid}",
    )


def parse_required_int(value, field_name, row_number):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise CommandError(
            f"{field_name} must be an integer at row {row_number}."
        ) from exc


def parse_required_uuid(value, field_name, row_number):
    text = str(value or "").strip()
    if not text:
        raise CommandError(f"{field_name} is required at row {row_number}.")

    try:
        return uuid.UUID(text)
    except (TypeError, ValueError) as exc:
        raise CommandError(
            f"{field_name} must be a valid UUID at row {row_number}."
        ) from exc


def parse_optional_uuid(value, field_name, row_number):
    text = str(value or "").strip()
    if not text:
        return None

    try:
        return uuid.UUID(text)
    except (TypeError, ValueError) as exc:
        raise CommandError(
            f"{field_name} must be a valid UUID at row {row_number}."
        ) from exc


def parse_required_timestamp(value, field_name, row_number):
    text = str(value or "").strip()
    if not text:
        raise CommandError(f"{field_name} is required at row {row_number}.")

    parsed = parse_datetime(text)
    if parsed is None:
        raise CommandError(
            f"{field_name} must be a valid timestamp at row {row_number}."
        )

    if timezone.is_naive(parsed):
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed.astimezone(dt_timezone.utc)


def parse_required_json_object(value, field_name, row_number):
    text = str(value or "").strip()
    if not text:
        raise CommandError(f"{field_name} is required at row {row_number}.")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CommandError(
            f"{field_name} must contain valid JSON at row {row_number}."
        ) from exc

    if not isinstance(parsed, dict):
        raise CommandError(
            f"{field_name} must contain a JSON object at row {row_number}."
        )

    return parsed


def parse_required_text(value, field_name, row_number, max_length=None):
    text = str(value or "").strip()
    if not text:
        raise CommandError(f"{field_name} is required at row {row_number}.")

    if max_length is not None and len(text) > max_length:
        raise CommandError(
            f"{field_name} exceeds {max_length} characters at row {row_number}."
        )

    return text


def parse_optional_text(value, field_name, row_number, max_length=None):
    text = str(value or "").strip()
    if not text:
        return None

    if max_length is not None and len(text) > max_length:
        raise CommandError(
            f"{field_name} exceeds {max_length} characters at row {row_number}."
        )

    return text


def iter_csv_rows(path, expected_columns, optional_columns=None):
    optional_columns = optional_columns or []
    allowed_columns = [expected_columns]
    if optional_columns:
        allowed_columns.append(expected_columns + optional_columns)

    try:
        with path.open("r", encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            if reader.fieldnames not in allowed_columns:
                raise CommandError(
                    f"{path.name} has unexpected columns. "
                    f"Expected one of {allowed_columns}, got {reader.fieldnames}."
                )

            for row_number, row in enumerate(reader, start=2):
                yield row_number, row
    except OSError as exc:
        raise CommandError(f"Could not read {path}: {exc}") from exc


class Command(BaseCommand):
    help = "Import a generated synthetic analytics dataset into a project."

    def add_arguments(self, parser):
        parser.add_argument(
            "dataset_dir",
            help="Directory containing tracker_analyticsevent.csv, tracker_analyticssession.csv, and page_rules.csv.",
        )
        parser.add_argument(
            "--project-id",
            type=int,
            help="Target project id.",
        )
        parser.add_argument(
            "--api-key",
            help="Target project API key. Required when --project-id is not provided.",
        )
        parser.add_argument(
            "--replace-existing",
            action="store_true",
            help="Delete existing analytics sessions/events, page rules, and page naming runs for the project first.",
        )
        parser.add_argument(
            "--created-by",
            choices=ProjectPageNamingRunMode.values,
            default=ProjectPageNamingRunMode.DAILY_STABLE,
            help="created_by value to store on imported ProjectPageRule rows.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=2000,
            help="Bulk insert batch size.",
        )
        parser.add_argument(
            "--events-offset",
            type=int,
            default=0,
            help=(
                "Number of event CSV rows to skip before importing. Use with "
                "--events-limit to import a large dataset in chunks."
            ),
        )
        parser.add_argument(
            "--events-limit",
            type=int,
            help="Maximum number of event CSV rows to import from --events-offset.",
        )
        parser.add_argument(
            "--append-events",
            action="store_true",
            help=(
                "Append an event chunk to a project that already has imported "
                "rules and sessions. Implies --skip-page-rules and --skip-sessions."
            ),
        )
        parser.add_argument(
            "--skip-page-rules",
            action="store_true",
            help="Reuse existing project page rules instead of importing page_rules.csv.",
        )
        parser.add_argument(
            "--skip-sessions",
            action="store_true",
            help="Reuse existing project sessions instead of importing tracker_analyticssession.csv.",
        )
        parser.add_argument(
            "--atomic",
            action="store_true",
            help=(
                "Wrap the whole import in one transaction. This is safer for small datasets "
                "but can exhaust memory/WAL on multi-million-row imports."
            ),
        )

    def handle(self, *args, **options):
        project = resolve_project(options["project_id"], options["api_key"])
        dataset_dir = Path(options["dataset_dir"]).expanduser().resolve()
        batch_size = max(int(options["batch_size"]), 1)
        events_offset = int(options["events_offset"])
        events_limit = options["events_limit"]
        if events_limit is not None:
            events_limit = int(events_limit)
        if events_offset < 0:
            raise CommandError("--events-offset must be zero or greater.")
        if events_limit is not None and events_limit < 1:
            raise CommandError("--events-limit must be greater than zero.")

        append_events = options["append_events"]
        skip_page_rules = bool(options["skip_page_rules"] or append_events)
        skip_sessions = bool(options["skip_sessions"] or append_events)
        if append_events and options["replace_existing"]:
            raise CommandError("--append-events cannot be combined with --replace-existing.")
        if options["replace_existing"] and (skip_page_rules or skip_sessions):
            raise CommandError(
                "--replace-existing cannot be combined with --skip-page-rules or --skip-sessions."
            )

        if not dataset_dir.exists() or not dataset_dir.is_dir():
            raise CommandError(f"Dataset directory was not found: {dataset_dir}")

        page_rules_path = dataset_dir / "page_rules.csv"
        sessions_path = dataset_dir / "tracker_analyticssession.csv"
        events_path = dataset_dir / "tracker_analyticsevent.csv"

        for path in (page_rules_path, sessions_path, events_path):
            if not path.exists():
                raise CommandError(f"Required dataset file is missing: {path}")

        if self._project_has_existing_data(project) and not (
            options["replace_existing"] or append_events
        ):
            raise CommandError(
                f"Project {project.id} already has analytics data or page rules. "
                "Use --replace-existing to reset it before importing, or "
                "--append-events to import the next event chunk."
            )

        source_rules = self._load_source_rules(page_rules_path)

        if options["atomic"]:
            with transaction.atomic():
                source_project_ids, rule_count, session_count, event_count = self._run_import(
                    project=project,
                    source_rules=source_rules,
                    sessions_path=sessions_path,
                    events_path=events_path,
                    replace_existing=options["replace_existing"],
                    created_by=options["created_by"],
                    batch_size=batch_size,
                    skip_page_rules=skip_page_rules,
                    skip_sessions=skip_sessions,
                    events_offset=events_offset,
                    events_limit=events_limit,
                )
        else:
            source_project_ids, rule_count, session_count, event_count = self._run_import(
                project=project,
                source_rules=source_rules,
                sessions_path=sessions_path,
                events_path=events_path,
                replace_existing=options["replace_existing"],
                created_by=options["created_by"],
                batch_size=batch_size,
                skip_page_rules=skip_page_rules,
                skip_sessions=skip_sessions,
                events_offset=events_offset,
                events_limit=events_limit,
            )

        source_project_ids_text = (
            ", ".join(str(project_id) for project_id in sorted(source_project_ids))
            if source_project_ids
            else "(sessions reused)"
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported synthetic analytics dataset into project {project.id} \"{project.name}\"."
            )
        )
        self.stdout.write(f"- source session project_ids: {source_project_ids_text}")
        self.stdout.write(f"- rules imported: {rule_count}")
        self.stdout.write(f"- sessions imported: {session_count}")
        self.stdout.write(f"- events imported: {event_count}")

    def _run_import(
        self,
        *,
        project,
        source_rules,
        sessions_path,
        events_path,
        replace_existing,
        created_by,
        batch_size,
        skip_page_rules,
        skip_sessions,
        events_offset,
        events_limit,
    ):
        if replace_existing:
            self._clear_project_data(project)

        if skip_page_rules:
            db_rule_id_by_source_id = self._load_existing_rule_ids(project, source_rules)
            rule_count = 0
        else:
            db_rule_id_by_source_id = self._import_page_rules(
                project=project,
                source_rules=source_rules,
                created_by=created_by,
                batch_size=batch_size,
            )
            rule_count = len(source_rules)

        if skip_sessions:
            source_project_ids = set()
            session_count = 0
        else:
            source_project_ids, session_count = self._import_sessions(
                project=project,
                sessions_path=sessions_path,
                batch_size=batch_size,
            )
        event_count, first_event_at = self._import_events(
            project=project,
            events_path=events_path,
            source_rules=source_rules,
            db_rule_id_by_source_id=db_rule_id_by_source_id,
            batch_size=batch_size,
            events_offset=events_offset,
            events_limit=events_limit,
        )

        if first_event_at is not None:
            ensure_project_first_event_at(project, first_event_at)

        return source_project_ids, rule_count, session_count, event_count

    def _project_has_existing_data(self, project):
        return (
            AnalyticsSession.objects.filter(project=project).exists()
            or ProjectPageRule.objects.filter(project=project).exists()
            or ProjectPageNamingRun.objects.filter(project=project).exists()
        )

    def _clear_project_data(self, project):
        event_table = connection.ops.quote_name(AnalyticsEvent._meta.db_table)
        session_table = connection.ops.quote_name(AnalyticsSession._meta.db_table)
        project_id_column = connection.ops.quote_name("project_id")
        session_id_column = connection.ops.quote_name("session_id")

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                DELETE FROM {event_table}
                WHERE {session_id_column} IN (
                    SELECT {session_id_column}
                    FROM {session_table}
                    WHERE {project_id_column} = %s
                )
                """,
                [project.id],
            )
            cursor.execute(
                f"DELETE FROM {session_table} WHERE {project_id_column} = %s",
                [project.id],
            )

        ProjectPageRule.objects.filter(project=project).delete()
        ProjectPageNamingRun.objects.filter(project=project).delete()

        if project.page_naming_first_event_at is not None:
            project.page_naming_first_event_at = None
            project.save(update_fields=["page_naming_first_event_at"])

    def _load_source_rules(self, page_rules_path):
        source_rules = []
        source_ids = set()
        patterns = set()

        for row_number, row in iter_csv_rows(
            page_rules_path,
            PAGE_RULE_COLUMNS,
            optional_columns=OPTIONAL_PAGE_RULE_COLUMNS,
        ):
            source_rule_id = parse_required_int(row["page_rule_id"], "page_rule_id", row_number)
            if source_rule_id in source_ids:
                raise CommandError(f"Duplicate page_rule_id {source_rule_id} in {page_rules_path.name}.")
            source_ids.add(source_rule_id)

            pattern = parse_required_text(row["pattern"], "pattern", row_number)
            if pattern in patterns:
                raise CommandError(f"Duplicate pattern {pattern!r} in {page_rules_path.name}.")
            patterns.add(pattern)

            try:
                compiled_pattern = re2.compile(pattern)
            except re2.error as exc:
                raise CommandError(
                    f"pattern is not a valid RE2 regex at row {row_number}: {exc}"
                ) from exc

            page_name = parse_required_text(
                row["page_name"],
                "page_name",
                row_number,
                max_length=255,
            )
            source_rules.append(
                {
                    "source_id": source_rule_id,
                    "pattern": pattern,
                    "page_normalized": parse_required_text(
                        row["page_normalized"],
                        "page_normalized",
                        row_number,
                    ),
                    "product_area": (
                        parse_optional_text(
                            row.get("product_area"),
                            "product_area",
                            row_number,
                            max_length=255,
                        )
                        or page_name
                    ),
                    "page_name": page_name,
                    "priority": parse_required_int(row["priority"], "priority", row_number),
                    "compiled_pattern": compiled_pattern,
                }
            )

        if not source_rules:
            raise CommandError("page_rules.csv does not contain any rows.")

        return source_rules

    def _import_page_rules(self, project, source_rules, created_by, batch_size):
        created_rules = ProjectPageRule.objects.bulk_create(
            [
                ProjectPageRule(
                    project=project,
                    pattern=rule["pattern"],
                    product_area=rule["product_area"],
                    page_name=rule["page_name"],
                    priority=rule["priority"],
                    is_active=True,
                    created_by=created_by,
                )
                for rule in source_rules
            ],
            batch_size=batch_size,
        )

        return {
            source_rule["source_id"]: created_rule.id
            for source_rule, created_rule in zip(source_rules, created_rules)
        }

    def _load_existing_rule_ids(self, project, source_rules):
        existing_rules = {
            rule.pattern: rule
            for rule in ProjectPageRule.objects.filter(project=project)
        }
        db_rule_id_by_source_id = {}
        missing_patterns = []
        mismatches = []

        for source_rule in source_rules:
            existing_rule = existing_rules.get(source_rule["pattern"])
            if existing_rule is None:
                missing_patterns.append(source_rule["pattern"])
                continue

            if existing_rule.page_name != source_rule["page_name"]:
                mismatches.append(
                    f"{source_rule['pattern']!r}: page_name "
                    f"{existing_rule.page_name!r} != {source_rule['page_name']!r}"
                )
            elif existing_rule.product_area != source_rule["product_area"]:
                mismatches.append(
                    f"{source_rule['pattern']!r}: product_area "
                    f"{existing_rule.product_area!r} != {source_rule['product_area']!r}"
                )

            db_rule_id_by_source_id[source_rule["source_id"]] = existing_rule.id

        if missing_patterns:
            sample = ", ".join(repr(pattern) for pattern in missing_patterns[:3])
            raise CommandError(
                "Existing project page rules do not match page_rules.csv; "
                f"missing patterns: {sample}."
            )
        if mismatches:
            raise CommandError(
                "Existing project page rules do not match page_rules.csv; "
                f"{mismatches[0]}."
            )

        return db_rule_id_by_source_id

    def _import_sessions(self, project, sessions_path, batch_size):
        batch = []
        source_project_ids = set()
        session_count = 0

        for row_number, row in iter_csv_rows(sessions_path, SESSION_COLUMNS):
            source_session_id = parse_required_uuid(row["session_id"], "session_id", row_number)
            visitor_guid = parse_optional_uuid(row["visitor_guid"], "visitor_guid", row_number)
            user_id = parse_required_text(row["user_id"], "user_id", row_number, max_length=255)
            company_id = parse_required_text(row["company_id"], "company_id", row_number, max_length=255)
            start_time = parse_required_timestamp(row["start_time"], "start_time", row_number)
            last_activity = parse_required_timestamp(row["last_activity"], "last_activity", row_number)
            ended_at = parse_required_timestamp(row["ended_at"], "ended_at", row_number)
            source_project_id = parse_required_int(row["project_id"], "project_id", row_number)
            source_project_ids.add(source_project_id)
            target_session_id = build_project_scoped_uuid(project.id, "session", source_session_id)

            if last_activity < start_time:
                raise CommandError(
                    f"last_activity is earlier than start_time at row {row_number}."
                )
            if ended_at < last_activity:
                raise CommandError(
                    f"ended_at is earlier than last_activity at row {row_number}."
                )

            batch.append(
                AnalyticsSession(
                    session_id=target_session_id,
                    project=project,
                    visitor_guid=visitor_guid,
                    user_id=user_id,
                    company_id=company_id,
                    start_time=start_time,
                    last_activity=last_activity,
                    ended_at=ended_at,
                )
            )
            session_count += 1

            if len(batch) >= batch_size:
                AnalyticsSession.objects.bulk_create(batch, batch_size=batch_size)
                batch.clear()
                if session_count % 100000 == 0:
                    self.stdout.write(f"  sessions imported: {session_count:,}")

        if batch:
            AnalyticsSession.objects.bulk_create(batch, batch_size=batch_size)

        if session_count == 0:
            raise CommandError("tracker_analyticssession.csv does not contain any rows.")

        return source_project_ids, session_count

    def _import_events(
        self,
        project,
        events_path,
        source_rules,
        db_rule_id_by_source_id,
        batch_size,
        events_offset,
        events_limit,
    ):
        source_rule_by_id = {
            rule["source_id"]: rule
            for rule in source_rules
        }
        batch = []
        event_count = 0
        first_event_at = None

        for row_number, row in iter_csv_rows(
            events_path,
            EVENT_COLUMNS,
            optional_columns=OPTIONAL_EVENT_COLUMNS,
        ):
            event_row_index = row_number - 2
            if event_row_index < events_offset:
                continue
            if events_limit is not None and event_count >= events_limit:
                break

            parse_required_int(row["id"], "id", row_number)
            event_type = parse_required_text(row["event_type"], "event_type", row_number, max_length=32)
            if event_type not in ALLOWED_EVENT_TYPES:
                raise CommandError(
                    f"Unsupported event_type {event_type!r} at row {row_number}."
                )

            timestamp = parse_required_timestamp(row["timestamp"], "timestamp", row_number)
            visitor_guid = parse_optional_uuid(row["visitor_guid"], "visitor_guid", row_number)
            user_id = parse_required_text(row["user_id"], "user_id", row_number, max_length=255)
            company_id = parse_required_text(row["company_id"], "company_id", row_number, max_length=255)
            user_traits = parse_required_json_object(row["user_traits"], "user_traits", row_number)
            company_traits = parse_required_json_object(row["company_traits"], "company_traits", row_number)
            element_key = parse_optional_text(row["element_key"], "element_key", row_number, max_length=300)
            page = parse_required_text(row["page"], "page", row_number)
            parse_required_text(row["page_normalized"], "page_normalized", row_number)
            page_name = parse_required_text(row["page_name"], "page_name", row_number, max_length=255)
            product_area = (
                parse_optional_text(
                    row.get("product_area"),
                    "product_area",
                    row_number,
                    max_length=255,
                )
                or page_name
            )
            origin_page_title = parse_required_text(
                row["origin_page_title"],
                "origin_page_title",
                row_number,
                max_length=255,
            )
            source_session_id = parse_required_uuid(row["session_id"], "session_id", row_number)
            source_page_rule_id = parse_required_int(row["page_rule_id"], "page_rule_id", row_number)
            target_session_id = build_project_scoped_uuid(project.id, "session", source_session_id)

            source_rule = source_rule_by_id.get(source_page_rule_id)
            if source_rule is None:
                raise CommandError(
                    f"Unknown page_rule_id {source_page_rule_id} at row {row_number}."
                )
            if page_name != source_rule["page_name"]:
                raise CommandError(
                    f"page_name does not match page_rules.csv for page_rule_id {source_page_rule_id} at row {row_number}."
                )
            if product_area != source_rule["product_area"]:
                raise CommandError(
                    f"product_area does not match page_rules.csv for page_rule_id {source_page_rule_id} at row {row_number}."
                )

            normalized_page = normalize_page_url_key(page)
            matching_rules = [
                rule
                for rule in source_rules
                if _regex_fullmatch(rule["compiled_pattern"], normalized_page)
            ]
            if len(matching_rules) != 1:
                raise CommandError(
                    f"URL {page!r} matched {len(matching_rules)} source rules at row {row_number}."
                )
            if matching_rules[0]["source_id"] != source_page_rule_id:
                raise CommandError(
                    f"URL {page!r} matched page_rule_id {matching_rules[0]['source_id']} "
                    f"but the event row references {source_page_rule_id}."
                )

            batch.append(
                AnalyticsEvent(
                    session_id=target_session_id,
                    event_type=event_type,
                    timestamp=timestamp,
                    visitor_guid=visitor_guid,
                    user_id=user_id,
                    company_id=company_id,
                    user_traits=user_traits,
                    company_traits=company_traits,
                    element_key=element_key,
                    url=page,
                    url_normalized=normalized_page,
                    product_area=product_area,
                    page_name=page_name,
                    page_name_original=origin_page_title,
                    page_rule_id=db_rule_id_by_source_id[source_page_rule_id],
                )
            )
            event_count += 1
            if first_event_at is None or timestamp < first_event_at:
                first_event_at = timestamp

            if len(batch) >= batch_size:
                AnalyticsEvent.objects.bulk_create(batch, batch_size=batch_size)
                batch.clear()
                if event_count % 100000 == 0:
                    self.stdout.write(f"  events imported: {event_count:,}")

        if batch:
            AnalyticsEvent.objects.bulk_create(batch, batch_size=batch_size)

        if event_count == 0:
            raise CommandError(
                "tracker_analyticsevent.csv does not contain any rows for "
                f"events_offset={events_offset} and events_limit={events_limit}."
            )

        return event_count, first_event_at
