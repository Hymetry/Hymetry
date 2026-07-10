import datetime
import json
import logging
from collections import Counter

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.projects.domain_utils import request_matches_allowed_domains
from apps.projects.models import Project
from apps.projects.services import record_project_production_event
from apps.tracker.models import AnalyticsEvent, AnalyticsSession
from apps.tracker.page_naming import (
    DEFAULT_PAGE_NAME,
    compile_page_rules,
    ensure_project_first_event_at,
    get_active_page_rules,
    normalize_page_url,
    normalize_page_url_key,
    resolve_project_page_name,
)
from apps.tracker.rrweb_text_filter import secure_mask_text_dynamic
from apps.tracker.visitor_ids import normalize_project_visitor_uuid

logger = logging.getLogger(__name__)


class AnalyticsTracker:
    """Handle analytics click ingestion and analytics sessionization."""

    def __init__(self, request):
        self.request = request
        self.data = None
        self.project = None
        self.batch = []
        self.accepted_events = 0
        self.skipped_events = 0
        self.touched_sessions = set()
        self.compiled_rules = []

    def parse_request(self):
        """Parse request JSON and validate API key."""
        try:
            self.data = json.loads(self.request.body or "{}")
        except json.JSONDecodeError:
            return False

        self.project = Project.active.select_related('workspace').filter(
            api_key=self.data.get('api_key'),
            workspace__archived_at__isnull=True,
        ).first()
        if self.project is None:
            raise PermissionDenied("You must provide a valid API_KEY")
        self.compiled_rules = compile_page_rules(get_active_page_rules(self.project))

        batch = self.data.get('batch', [])
        self.batch = batch if isinstance(batch, list) else []
        candidate_url = self._first_batch_page_url()
        if not request_matches_allowed_domains(self.request, self.project, candidate_url):
            raise PermissionDenied("Origin is not allowed for this project's allowed domains.")
        return True

    def _first_batch_page_url(self):
        for raw_event in self.batch:
            if not isinstance(raw_event, dict):
                continue
            page = raw_event.get('page')
            if isinstance(page, dict):
                return page.get('url') or ''
            if isinstance(page, str):
                return page
        return ''

    def _safe_string(self, value, max_length=None):
        if value is None:
            return None

        text = str(value).strip()
        if not text:
            return None

        if max_length:
            return text[:max_length]
        return text

    def _safe_page_value(self, value, max_length=None):
        text = self._safe_string(value, max_length=max_length)
        return text or ""

    def _extract_page(self, raw_page):
        if isinstance(raw_page, str):
            return self._safe_page_value(normalize_page_url(raw_page))

        if isinstance(raw_page, dict):
            return self._safe_page_value(normalize_page_url(raw_page.get('url')))

        return ""

    def _extract_page_name_original(self, raw_page):
        if isinstance(raw_page, dict):
            return self._safe_string(raw_page.get('title'), max_length=255) or ""
        return ""

    def _normalize_page(self, raw_page):
        return normalize_page_url_key(self._extract_page(raw_page))

    def _parse_timestamp(self, value):
        if isinstance(value, (int, float)):
            try:
                return datetime.datetime.fromtimestamp(value / 1000, tz=datetime.timezone.utc)
            except (OverflowError, OSError, ValueError):
                return timezone.now()

        if isinstance(value, str):
            parsed = parse_datetime(value)
            if parsed:
                if timezone.is_naive(parsed):
                    parsed = parsed.replace(tzinfo=datetime.timezone.utc)
                return parsed.astimezone(datetime.timezone.utc)

        return timezone.now()

    def _normalize_visitor_guid(self, value):
        if not self.project:
            return None
        return normalize_project_visitor_uuid(self.project.id, value)

    def _safe_traits(self, value):
        if not isinstance(value, dict):
            return {}

        try:
            return json.loads(json.dumps(value))
        except (TypeError, ValueError):
            return {}

    def _sanitize_element_key(self, value):
        text = self._safe_string(value, max_length=300)
        if text is None:
            return None

        prefix, separator, suffix = text.partition(':')
        if separator and suffix.strip():
            masked_suffix = secure_mask_text_dynamic(suffix.strip())
            return self._safe_string(f'{prefix}{separator} {masked_suffix}', max_length=300)

        return self._safe_string(secure_mask_text_dynamic(text), max_length=300)

    def _normalize_event(self, raw_event):
        if not isinstance(raw_event, dict):
            return None

        raw_user = raw_event.get('user')
        raw_company = raw_event.get('company')
        raw_page = raw_event.get('page')

        user = raw_user if isinstance(raw_user, dict) else {}
        company = raw_company if isinstance(raw_company, dict) else {}
        page = self._extract_page(raw_page)
        page_normalized = self._normalize_page(raw_page)
        page_name_original = self._extract_page_name_original(raw_page)

        fallback_visitor = self.data.get('visitor_id') if isinstance(self.data, dict) else None
        visitor_guid = self._normalize_visitor_guid(raw_event.get('visitor_id') or fallback_visitor)
        event_type = self._safe_string(raw_event.get('type'), max_length=32) or 'click'
        timestamp = self._parse_timestamp(raw_event.get('ts'))
        user_id = self._safe_string(
            raw_event.get('user_id') if raw_event.get('user_id') is not None else user.get('id'),
            max_length=255,
        )
        company_id = self._safe_string(
            raw_event.get('company_id') if raw_event.get('company_id') is not None else company.get('id'),
            max_length=255,
        )
        element_key = self._sanitize_element_key(
            raw_event.get('elementKey') if raw_event.get('elementKey') is not None else raw_event.get('element_key'),
        )
        user_traits = self._safe_traits(
            raw_event.get('user_traits') if raw_event.get('user_traits') is not None else user.get('traits')
        )
        company_traits = self._safe_traits(
            raw_event.get('company_traits') if raw_event.get('company_traits') is not None else company.get('traits')
        )

        return {
            'event_type': event_type,
            'timestamp': timestamp,
            'visitor_guid': visitor_guid,
            'user_id': user_id,
            'company_id': company_id,
            'user_traits': user_traits,
            'company_traits': company_traits,
            'element_key': element_key,
            'url': page,
            'url_normalized': page_normalized,
            'page_name_original': page_name_original,
        }

    def _session_timeout(self):
        return datetime.timedelta(
            seconds=getattr(settings, 'ANALYTICS_SESSION_EXPIRATION_SECONDS', 1800)
        )

    def _get_open_session(self, normalized_event):
        return AnalyticsSession.objects.filter(
            project=self.project,
            visitor_guid=normalized_event['visitor_guid'],
            user_id=normalized_event['user_id'],
            company_id=normalized_event['company_id'],
            ended_at__isnull=True,
        ).order_by('-last_activity').first()

    def _get_or_create_session(self, normalized_event):
        event_time = normalized_event['timestamp']
        timeout = self._session_timeout()
        session = self._get_open_session(normalized_event)

        if session:
            reference_time = session.last_activity or session.start_time
            if reference_time and event_time > reference_time + timeout:
                # This session expired before the current event; close it and start a new one.
                ended_at = reference_time + timeout
                session.ended_at = ended_at
                session.save(update_fields=['ended_at'])
                session = None

        if not session:
            session = AnalyticsSession.objects.create(
                project=self.project,
                visitor_guid=normalized_event['visitor_guid'],
                user_id=normalized_event['user_id'],
                company_id=normalized_event['company_id'],
                start_time=event_time,
                last_activity=event_time,
            )
        elif event_time > session.last_activity:
            session.last_activity = event_time
            session.save(update_fields=['last_activity'])

        self.touched_sessions.add(str(session.session_id))
        return session

    def _log_ingested_batch(self, event_type_counts, sample_event):
        if not sample_event or self.accepted_events <= 0:
            return

        event_types_summary = ",".join(
            f"{event_type}:{event_type_counts[event_type]}"
            for event_type in sorted(event_type_counts)
        )

        logger.info(
            "Analytics batch ingested project_id=%s accepted=%s skipped=%s sessions_touched=%s "
            "event_types=%s visitor_guid=%s sample_url=%s sample_title=%s",
            self.project.id if self.project else None,
            self.accepted_events,
            self.skipped_events,
            len(self.touched_sessions),
            event_types_summary,
            sample_event['visitor_guid'],
            sample_event['url_normalized'],
            sample_event['page_name_original'],
        )

    def process_events(self):
        event_objects = []
        first_event_time = None
        last_event_time = None
        event_type_counts = Counter()
        sample_event = None

        for raw_event in self.batch:
            normalized_event = self._normalize_event(raw_event)
            if normalized_event is None:
                self.skipped_events += 1
                continue

            session = self._get_or_create_session(normalized_event)
            page_rule, product_area, page_name = resolve_project_page_name(
                self.project,
                normalized_event['url'],
                compiled_rules=self.compiled_rules,
            )
            event_time = normalized_event['timestamp']
            if first_event_time is None or event_time < first_event_time:
                first_event_time = event_time
            if last_event_time is None or event_time > last_event_time:
                last_event_time = event_time
            event_type_counts[normalized_event['event_type']] += 1
            if sample_event is None:
                sample_event = normalized_event
            event_objects.append(
                AnalyticsEvent(
                    session=session,
                    event_type=normalized_event['event_type'],
                    timestamp=event_time,
                    visitor_guid=normalized_event['visitor_guid'],
                    user_id=normalized_event['user_id'],
                    company_id=normalized_event['company_id'],
                    user_traits=normalized_event['user_traits'],
                    company_traits=normalized_event['company_traits'],
                    element_key=normalized_event['element_key'],
                    url=normalized_event['url'],
                    url_normalized=normalized_event['url_normalized'],
                    product_area=product_area,
                    page_name=page_name or DEFAULT_PAGE_NAME,
                    page_name_original=normalized_event['page_name_original'],
                    page_rule=page_rule,
                )
            )
            self.accepted_events += 1

        if event_objects:
            AnalyticsEvent.objects.bulk_create(event_objects, batch_size=100)
            ensure_project_first_event_at(self.project, first_event_time)
            record_project_production_event(self.project, first_event_time, last_event_time)
            self._log_ingested_batch(event_type_counts, sample_event)

    def get_response(self):
        return JsonResponse({
            'status': 'success',
            'accepted_events': self.accepted_events,
            'skipped_events': self.skipped_events,
            'sessions_touched': len(self.touched_sessions),
        })
