import json
import logging
import random
import re
import time
from contextlib import contextmanager
from datetime import timedelta
from urllib.parse import urlparse

import openai
import re2
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Count, Min, Q
from django.utils import timezone
from openai import OpenAIError

from apps.projects.models import Project, ProjectPageNamingState
from apps.projects.ai_credentials import WorkspaceOpenAIKeyError, get_openai_api_key_for_project
from apps.projects.utils import normalize_capture_modes
from apps.tracker.models import (
    AnalyticsEvent,
    LLMUsageLog,
    ProjectPageNamingPhase,
    ProjectPageNamingRun,
    ProjectPageNamingRunMode,
    ProjectPageNamingRunStatus,
    ProjectPageRule,
    ProjectPageRuleVersion,
    TitlePrompt,
)

logger = logging.getLogger(__name__)
llm_usage_logger = logging.getLogger('llm_usage')

DEFAULT_PAGE_NAME = 'Undefined'
PAGE_NAMING_PROMPT_FIELD_BY_MODE = {
    ProjectPageNamingRunMode.HOURLY_UNSTABLE: 'hourly_unstable_prompt',
    ProjectPageNamingRunMode.DAILY_STABLE: 'daily_stable_prompt',
}
PAGE_NAMING_MODEL_FIELD_BY_MODE = {
    ProjectPageNamingRunMode.HOURLY_UNSTABLE: 'hourly_unstable_openai_model',
    ProjectPageNamingRunMode.DAILY_STABLE: 'daily_stable_openai_model',
}
PAGE_NAMING_PROMPT_FIELD_BY_PHASE = {
    ProjectPageNamingPhase.BOOTSTRAP: 'bootstrap_page_naming_prompt',
    ProjectPageNamingPhase.INCREMENTAL: 'hourly_unstable_prompt',
    ProjectPageNamingPhase.STABLE: 'daily_stable_prompt',
}
PAGE_NAMING_MODEL_FIELD_BY_PHASE = {
    ProjectPageNamingPhase.BOOTSTRAP: 'bootstrap_page_naming_openai_model',
    ProjectPageNamingPhase.INCREMENTAL: 'hourly_unstable_openai_model',
    ProjectPageNamingPhase.STABLE: 'daily_stable_openai_model',
}
AREA_ROLE_CHOICES = {'product', 'setup', 'admin', 'support', 'system', 'unknown'}
AREA_METADATA_PROMPT_GUIDANCE = """

Product area recommendation metadata guidance:

Each rule must include area_role and is_adoption_recommendable. Treat these fields as product-area attributes and use the same values for every rule with the same page_group unless the page group should be split.

area_role must be one of: product, setup, admin, support, system, unknown.
- product: meaningful product workflows or product modules that represent business/product usage.
- setup: onboarding/configuration areas such as integrations setup, API keys, data sources, imports, or webhooks.
- admin: account/service areas such as Settings, Team permissions, User management, Account profile, Payment methods, or subscription management.
- support: help, docs, support, tutorials, or contact support.
- system: auth, signup, password reset, errors, or system pages.
- unknown: use only when there is not enough evidence.

is_adoption_recommendable must be true only for meaningful product usage that product, success, sales, or account teams would reasonably want more users or companies to adopt. It should usually be false for settings, permissions, auth, profile, payment, support/help, purely technical setup, and unknown areas. Do not set it to true just because an area has high traffic.

Strict JSON rule objects must contain exactly: pattern, page_group, page_group_short_name, area_role, is_adoption_recommendable, page_name, priority.
"""


def _seconds_setting(name, default):
    return int(getattr(settings, name, default))


def _float_setting(name, default):
    return float(getattr(settings, name, default))


def get_prompt_url_limit():
    return int(getattr(settings, 'PAGE_NAMING_PROMPT_URL_LIMIT', 150))


def get_hybrid_top_limit():
    return int(getattr(settings, 'PAGE_NAMING_HYBRID_TOP_LIMIT', 100))


def get_hybrid_random_limit():
    return int(getattr(settings, 'PAGE_NAMING_HYBRID_RANDOM_LIMIT', 200))


def get_title_backfill_url_limit():
    return int(getattr(settings, 'PAGE_NAMING_TITLE_BACKFILL_URL_LIMIT', 100))


def get_short_window():
    return timedelta(seconds=_seconds_setting('PAGE_NAMING_NEW_URLS_SHORT_WINDOW_SECONDS', 60 * 60))


def get_long_window():
    return timedelta(seconds=_seconds_setting('PAGE_NAMING_NEW_URLS_LONG_WINDOW_SECONDS', 24 * 60 * 60))


def get_comparison_window():
    return timedelta(seconds=_seconds_setting('PAGE_NAMING_COMPARISON_WINDOW_SECONDS', 96 * 60 * 60))


def get_unstable_rewrite_window():
    return timedelta(seconds=_seconds_setting('PAGE_NAMING_UNSTABLE_REWRITE_WINDOW_SECONDS', 4 * 24 * 60 * 60))


def get_stable_input_window():
    return timedelta(seconds=_seconds_setting('PAGE_NAMING_STABLE_INPUT_WINDOW_SECONDS', 7 * 24 * 60 * 60))


def get_stable_after_soft_window():
    return timedelta(seconds=_seconds_setting('PAGE_NAMING_STABLE_AFTER_SOFT_SECONDS', 2 * 24 * 60 * 60))


def get_stable_after_hard_window():
    return timedelta(seconds=_seconds_setting('PAGE_NAMING_STABLE_AFTER_HARD_SECONDS', 4 * 24 * 60 * 60))


def get_stable_min_unique_urls():
    return int(getattr(settings, 'PAGE_NAMING_STABLE_MIN_UNIQUE_URLS', 10))


def get_stable_new_urls_threshold():
    return _float_setting('PAGE_NAMING_STABLE_NEW_URLS_24H_THRESHOLD', 5)


def get_unstable_new_urls_threshold():
    return _float_setting('PAGE_NAMING_UNSTABLE_NEW_URLS_24H_THRESHOLD', 30)


def get_bootstrap_success_runs_target():
    return int(getattr(settings, 'PAGE_NAMING_BOOTSTRAP_SUCCESS_RUNS', 2))


def normalize_page_url(url):
    """Normalize URLs for stable page naming and matching."""
    if not url:
        return ''

    text = str(url).strip()
    if not text:
        return ''

    parsed = urlparse(text)
    normalized = parsed._replace(query='', fragment='').geturl()
    if normalized.endswith('/') and parsed.path not in ('', '/'):
        normalized = normalized.rstrip('/')
    return normalized


def normalize_page_url_key(url):
    """Build a scheme-less canonical URL key for matching and analytics storage."""
    normalized_url = normalize_page_url(url)
    if not normalized_url:
        return ''

    if '://' in normalized_url:
        return normalized_url.split('://', 1)[1]
    if normalized_url.startswith('//'):
        return normalized_url[2:]
    return normalized_url


def truncate_url_for_prompt(url):
    prompt_url_limit = get_prompt_url_limit()
    if len(url) <= prompt_url_limit:
        return url
    return f"{url[:prompt_url_limit]}…"


def get_project_capture_modes(project):
    capture = normalize_capture_modes(project.tracking_capture)
    return {mode for mode in capture.split(',') if mode}


def project_uses_analytics(project):
    return 'analytics' in get_project_capture_modes(project)


def ensure_project_first_event_at(project, event_time):
    if not event_time:
        return

    if project.page_naming_first_event_at is None or event_time < project.page_naming_first_event_at:
        project.page_naming_first_event_at = event_time
        project.save(update_fields=['page_naming_first_event_at'])


def set_project_page_naming_state(project, state):
    if project.page_naming_state == state:
        return

    project.page_naming_state = state
    project.page_naming_state_changed_at = timezone.now()
    project.save(update_fields=['page_naming_state', 'page_naming_state_changed_at'])


def _delete_generated_product_areas(project_id):
    from apps.pages.models import ProductArea

    deleted_count, _ = ProductArea.objects.filter(
        project_id=project_id,
        source__in=(ProductArea.SOURCE_AI, ProductArea.SOURCE_SYSTEM),
    ).delete()
    return deleted_count


def reset_project_page_naming_to_bootstrap(project):
    project_id = _resolve_project_id(project)
    if not project_id:
        raise ValueError('Project id is required')

    reset_at = timezone.now()
    with transaction.atomic():
        locked_project = Project.objects.select_for_update().get(pk=project_id)
        rules_deactivated = ProjectPageRule.objects.filter(
            project_id=project_id,
            is_active=True,
        ).update(is_active=False)
        events_reset = AnalyticsEvent.objects.filter(session__project_id=project_id).update(
            product_area='',
            page_name=DEFAULT_PAGE_NAME,
            page_rule_id=None,
        )
        generated_product_areas_deleted = _delete_generated_product_areas(project_id)

        locked_project.page_naming_state = ProjectPageNamingState.NOT_STABLE
        locked_project.page_naming_state_changed_at = reset_at
        locked_project.page_naming_first_event_at = reset_at
        locked_project.save(update_fields=[
            'page_naming_state',
            'page_naming_state_changed_at',
            'page_naming_first_event_at',
        ])

    if isinstance(project, Project):
        project.page_naming_state = ProjectPageNamingState.NOT_STABLE
        project.page_naming_state_changed_at = reset_at
        project.page_naming_first_event_at = reset_at

    return {
        'project_id': project_id,
        'reset_at': reset_at,
        'rules_deactivated': rules_deactivated,
        'events_reset': events_reset,
        'generated_product_areas_deleted': generated_product_areas_deleted,
    }


def _regex_fullmatch(compiled_pattern, url):
    if hasattr(compiled_pattern, 'fullmatch'):
        return compiled_pattern.fullmatch(url)

    match = compiled_pattern.match(url)
    if not match:
        return None
    return match if match.group(0) == url else None


def _sorted_rules(rules):
    return sorted(rules, key=lambda rule: (-rule.priority, -len(rule.pattern), rule.id))


def get_active_page_rules(project):
    return list(
        ProjectPageRule.objects.filter(project=project, is_active=True).order_by('-priority', '-updated_at', 'id')
    )


def compile_page_rules(rules):
    compiled_rules = []
    invalid_rule_ids = []

    for rule in _sorted_rules(rules):
        try:
            compiled_rules.append((rule, re2.compile(rule.pattern)))
        except re2.error as exc:
            invalid_rule_ids.append(rule.id)
            logger.warning("Invalid page naming regex for rule %s: %s", rule.id, exc)

    if invalid_rule_ids:
        ProjectPageRule.objects.filter(id__in=invalid_rule_ids).update(is_active=False)

    return compiled_rules


def normalize_product_area(product_area, page_name):
    normalized_page_name = str(page_name or '').strip()
    normalized_product_area = str(product_area or '').strip()
    return (normalized_product_area or normalized_page_name)[:255]


def normalize_product_area_short_name(short_name, product_area):
    normalized_short_name = str(short_name or '').strip()
    normalized_product_area = str(product_area or '').strip()
    return (normalized_short_name or normalized_product_area)[:64]


def resolve_page_rule_match(url, compiled_rules=None):
    normalized_url = normalize_page_url_key(url)
    if not normalized_url:
        return None, '', DEFAULT_PAGE_NAME

    compiled_rules = compiled_rules or []

    has_rules = bool(compiled_rules)
    for rule, compiled_pattern in compiled_rules:
        if _regex_fullmatch(compiled_pattern, normalized_url):
            return rule, normalize_product_area(getattr(rule, 'product_area', ''), rule.page_name), rule.page_name

    if has_rules:
        return None, '', DEFAULT_PAGE_NAME

    return None, '', ''


def resolve_project_page_name(project, url, compiled_rules=None):
    if compiled_rules is None:
        compiled_rules = compile_page_rules(get_active_page_rules(project))
    return resolve_page_rule_match(url, compiled_rules=compiled_rules)


def sample_urls_need_rule_refresh(urls, rules):
    if not urls:
        return False
    if not rules:
        return True

    compiled_rules = compile_page_rules(rules)
    if not compiled_rules:
        return True

    for url in urls:
        rule, _, _ = resolve_page_rule_match(url, compiled_rules=compiled_rules)
        if rule is None:
            return True

    return False


class BasePageNamingSourceAdapter:
    def __init__(self, project):
        self.project = project

    def events_count_since(self, since):
        raise NotImplementedError

    def events_count_between(self, start_time, end_time=None):
        raise NotImplementedError

    def first_event_at(self):
        raise NotImplementedError

    def unique_urls_total(self):
        raise NotImplementedError

    def distinct_urls_between(self, start_time, end_time=None):
        raise NotImplementedError

    def ranked_urls_with_counts(self, start_time=None, end_time=None):
        raise NotImplementedError

    def events_exist_last_hour(self, now=None):
        now = now or timezone.now()
        return self.events_count_between(now - get_short_window(), now) > 0

    def distinct_urls_since(self, since):
        return self.distinct_urls_between(since)


class AnalyticsSourceAdapter(BasePageNamingSourceAdapter):
    def _base_queryset(self):
        return AnalyticsEvent.objects.filter(session__project=self.project)

    def _normalized_queryset(self):
        return self._base_queryset().exclude(url_normalized='')

    def events_count_since(self, since):
        return self.events_count_between(since)

    def events_count_between(self, start_time, end_time=None):
        queryset = self._base_queryset().filter(timestamp__gte=start_time)
        if end_time is not None:
            queryset = queryset.filter(timestamp__lt=end_time)
        return queryset.count()

    def first_event_at(self):
        return self._base_queryset().aggregate(first_seen=Min('timestamp'))['first_seen']

    def unique_urls_total(self):
        return self._normalized_queryset().values('url_normalized').distinct().count()

    def distinct_urls_between(self, start_time, end_time=None):
        queryset = self._normalized_queryset().filter(timestamp__gte=start_time)
        if end_time is not None:
            queryset = queryset.filter(timestamp__lt=end_time)
        return set(queryset.values_list('url_normalized', flat=True).distinct())

    def ranked_urls_with_counts(self, start_time=None, end_time=None):
        queryset = self._normalized_queryset()
        if start_time is not None:
            queryset = queryset.filter(timestamp__gte=start_time)
        if end_time is not None:
            queryset = queryset.filter(timestamp__lt=end_time)

        return list(
            queryset.values('url_normalized')
            .annotate(total=Count('id'))
            .order_by('-total', 'url_normalized')
        )

def get_source_adapter(project):
    return AnalyticsSourceAdapter(project)


def _unresolved_analytics_titles_queryset(project):
    return (
        AnalyticsEvent.objects
        .filter(session__project=project, page_rule_id__isnull=True)
        .exclude(url_normalized='')
        .filter(
            Q(page_name=DEFAULT_PAGE_NAME)
            | Q(page_name='')
            | Q(product_area='')
        )
    )


def build_title_backfill_urls(project, limit=None):
    limit = get_title_backfill_url_limit() if limit is None else limit
    ranked_urls = (
        _unresolved_analytics_titles_queryset(project)
        .values('url_normalized')
        .annotate(total=Count('id'))
        .order_by('-total', 'url_normalized')
    )

    if limit is not None:
        ranked_urls = ranked_urls[:limit]

    return [
        normalize_page_url_key(entry.get('url_normalized') or '')
        for entry in ranked_urls
        if normalize_page_url_key(entry.get('url_normalized') or '')
    ]


def apply_rules_to_unresolved_analytics_events(project, rules):
    compiled_rules = compile_page_rules(rules)
    if not compiled_rules:
        return 0

    queryset = _unresolved_analytics_titles_queryset(project)
    updates = []

    for analytics_event in queryset.only('id', 'url', 'url_normalized', 'product_area', 'page_name', 'page_rule_id'):
        normalized_url = normalize_page_url_key(analytics_event.url_normalized or analytics_event.url)
        rule, product_area, page_name = resolve_page_rule_match(normalized_url, compiled_rules=compiled_rules)
        if rule is None:
            continue

        analytics_event.url_normalized = normalized_url
        analytics_event.product_area = product_area
        analytics_event.page_name = page_name or DEFAULT_PAGE_NAME
        analytics_event.page_rule_id = rule.id
        updates.append(analytics_event)

    if updates:
        AnalyticsEvent.objects.bulk_update(
            updates,
            ['url_normalized', 'product_area', 'page_name', 'page_rule'],
            batch_size=500,
        )

    return len(updates)


def calculate_new_url_metrics(adapter, now=None):
    now = now or timezone.now()
    short_window = get_short_window()
    long_window = get_long_window()
    comparison_window = get_comparison_window()
    last_short_window_start = now - short_window
    last_long_window_start = now - long_window

    # We exclude the current comparison window from the reference set.
    # If we include it literally, the delta set collapses to zero.
    previous_comparison_for_short_window = adapter.distinct_urls_between(
        last_short_window_start - comparison_window,
        last_short_window_start,
    )
    previous_comparison_for_long_window = adapter.distinct_urls_between(
        last_long_window_start - comparison_window,
        last_long_window_start,
    )
    urls_last_short_window = adapter.distinct_urls_between(last_short_window_start, now)
    urls_last_long_window = adapter.distinct_urls_between(last_long_window_start, now)

    new_urls_1h = len(urls_last_short_window - previous_comparison_for_short_window)
    new_urls_last_day = urls_last_long_window - previous_comparison_for_long_window
    dataset2_size = max(len(previous_comparison_for_long_window), 1)
    new_urls_24h = (len(new_urls_last_day) / dataset2_size) * 100

    return {
        'new_urls_1h': new_urls_1h,
        'new_urls_24h': new_urls_24h,
        'urls_last_hour': urls_last_short_window,
        'urls_last_day': urls_last_long_window,
        'events_1h': adapter.events_count_between(last_short_window_start, now),
    }


def build_hybrid_urls(project, adapter, now=None, start_time=None, top_limit=None, random_limit=None):
    now = now or timezone.now()
    top_limit = get_hybrid_top_limit() if top_limit is None else top_limit
    random_limit = get_hybrid_random_limit() if random_limit is None else random_limit
    ranked_urls = adapter.ranked_urls_with_counts(start_time=start_time, end_time=now)
    top_urls = []
    top_url_set = set()
    all_urls = []

    for entry in ranked_urls:
        url = entry.get('url_normalized') or ''
        normalized_url = normalize_page_url_key(url)
        if not normalized_url:
            continue
        all_urls.append(normalized_url)
        if len(top_urls) < top_limit and normalized_url not in top_url_set:
            top_urls.append(normalized_url)
            top_url_set.add(normalized_url)

    unique_all_urls = list(dict.fromkeys(all_urls))
    random_candidates = [url for url in unique_all_urls if url not in top_url_set]
    randomizer = random.Random(f"{project.id}:{start_time or 'all'}:{now.isoformat()}")

    if random_candidates:
        sample_size = min(random_limit, len(random_candidates))
        random_urls = randomizer.sample(random_candidates, sample_size)
    else:
        random_urls = []

    return list(dict.fromkeys(top_urls + random_urls))


def _default_page_naming_phase_for_mode(mode):
    if mode == ProjectPageNamingRunMode.DAILY_STABLE:
        return ProjectPageNamingPhase.STABLE
    if mode == ProjectPageNamingRunMode.HOURLY_TITLE_BACKFILL:
        return ProjectPageNamingPhase.BACKFILL
    return ProjectPageNamingPhase.INCREMENTAL


def _bootstrap_rule_versions_count_since_state_change(project):
    queryset = ProjectPageRuleVersion.objects.filter(
        project=project,
        mode=ProjectPageNamingRunMode.HOURLY_UNSTABLE,
        phase=ProjectPageNamingPhase.BOOTSTRAP,
    )
    if project.page_naming_state_changed_at:
        queryset = queryset.filter(created_at__gte=project.page_naming_state_changed_at)
    return queryset.count()


def resolve_hourly_unstable_page_naming_phase(project):
    if project.page_naming_state != ProjectPageNamingState.NOT_STABLE:
        return ProjectPageNamingPhase.INCREMENTAL
    if _bootstrap_rule_versions_count_since_state_change(project) < get_bootstrap_success_runs_target():
        return ProjectPageNamingPhase.BOOTSTRAP
    return ProjectPageNamingPhase.INCREMENTAL


def _get_prompt_field_name(mode, phase=None):
    if phase in PAGE_NAMING_PROMPT_FIELD_BY_PHASE:
        return PAGE_NAMING_PROMPT_FIELD_BY_PHASE[phase]
    return PAGE_NAMING_PROMPT_FIELD_BY_MODE[mode]


def _get_model_field_name(mode, phase=None):
    if phase in PAGE_NAMING_MODEL_FIELD_BY_PHASE:
        return PAGE_NAMING_MODEL_FIELD_BY_PHASE[phase]
    return PAGE_NAMING_MODEL_FIELD_BY_MODE[mode]


def _get_page_naming_openai_model_name(mode, prompt=None, phase=None):
    prompt = prompt or get_active_title_prompt()
    if not prompt:
        raise RuntimeError('TitlePrompt configuration is missing')

    prompt_model_field_name = _get_model_field_name(mode, phase=phase)
    prompt_model_name = (getattr(prompt, prompt_model_field_name, '') or '').strip()
    if not prompt_model_name:
        raise RuntimeError(f'TitlePrompt.{prompt_model_field_name} is empty')
    return prompt_model_name


def get_active_title_prompt():
    return TitlePrompt.objects.order_by('id').first()


def build_prompt_version(prompt):
    return f"db-{prompt.id}-{prompt.updated_at:%Y%m%d%H%M%S}"


def _resolve_project_id(project):
    if isinstance(project, Project):
        return project.id
    return getattr(project, 'id', None)


def _coerce_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'true', '1', 'yes'}:
            return True
        if normalized in {'false', '0', 'no', ''}:
            return False
    return bool(value)


def _normalize_prompt_rules(rules):
    normalized_rules = []

    for entry in rules or []:
        if isinstance(entry, dict):
            source = entry
        else:
            source = {
                'pattern': getattr(entry, 'pattern', ''),
                'page_group': getattr(entry, 'product_area', ''),
                'page_group_short_name': getattr(entry, 'product_area_short_name', ''),
                'area_role': getattr(entry, 'area_role', 'unknown'),
                'is_adoption_recommendable': getattr(entry, 'is_adoption_recommendable', False),
                'page_name': getattr(entry, 'page_name', ''),
                'priority': getattr(entry, 'priority', 100),
            }

        pattern = str(source.get('pattern', '')).strip()
        page_name = str(source.get('page_name', '')).strip()
        page_group = str(source.get('page_group', '')).strip()[:255]
        page_group_short_name = str(source.get('page_group_short_name', '')).strip()[:64]
        area_role = str(source.get('area_role') or 'unknown').strip().lower()
        is_adoption_recommendable = _coerce_bool(source.get('is_adoption_recommendable', False))
        priority = source.get('priority', 100)

        if not pattern or not page_group or not page_group_short_name or not page_name:
            continue
        if area_role not in AREA_ROLE_CHOICES:
            area_role = 'unknown'

        try:
            priority = int(priority)
        except (TypeError, ValueError):
            priority = 100

        normalized_rules.append({
            'pattern': pattern,
            'page_group': page_group,
            'page_group_short_name': page_group_short_name,
            'area_role': area_role,
            'is_adoption_recommendable': is_adoption_recommendable,
            'page_name': page_name[:255],
            'priority': priority,
        })

    return normalized_rules


def _normalize_prompt_urls(urls):
    normalized_urls = []

    for url in urls or []:
        normalized_url = normalize_page_url_key(url)
        if normalized_url:
            normalized_urls.append(normalized_url)

    return list(dict.fromkeys(normalized_urls))


def _get_latest_original_titles_by_normalized_url(project, urls):
    normalized_urls = _normalize_prompt_urls(urls)
    if not normalized_urls:
        return {}

    project_id = _resolve_project_id(project)
    if not project_id:
        return {url: '' for url in normalized_urls}

    title_map = {}
    queryset = (
        AnalyticsEvent.objects
        .filter(session__project_id=project_id, url_normalized__in=normalized_urls)
        .order_by('url_normalized', '-timestamp', '-id')
        .values('url_normalized', 'page_name_original')
    )

    for row in queryset.iterator(chunk_size=2000):
        normalized_url = (row.get('url_normalized') or '').strip()
        if not normalized_url or normalized_url in title_map:
            continue
        title_map[normalized_url] = (row.get('page_name_original') or '').strip()
        if len(title_map) == len(normalized_urls):
            break

    for normalized_url in normalized_urls:
        title_map.setdefault(normalized_url, '')

    return title_map


def build_observed_pages_for_prompt(project, urls):
    normalized_urls = _normalize_prompt_urls(urls)
    title_map = _get_latest_original_titles_by_normalized_url(project, normalized_urls)

    return [
        {
            'url': truncate_url_for_prompt(normalized_url),
            'page_title': title_map.get(normalized_url, ''),
        }
        for normalized_url in normalized_urls
    ]


def render_prompt_template(prompt_text, context):
    rendered = prompt_text
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def _build_prompt(mode, project, urls, existing_rules=None, prompt=None, phase=None):
    current_structure = _normalize_prompt_rules(existing_rules)
    current_structure_text = json.dumps(current_structure, ensure_ascii=False)
    observed_pages_text = json.dumps(build_observed_pages_for_prompt(project, urls), ensure_ascii=False)
    user_modification_request = (getattr(project, 'page_structure_guidance', '') or '').strip()
    prompt = prompt or get_active_title_prompt()
    if not prompt:
        raise RuntimeError('TitlePrompt configuration is missing')
    prompt_field_name = _get_prompt_field_name(mode, phase=phase)
    prompt_text = getattr(prompt, prompt_field_name, '')
    if not prompt_text.strip():
        raise RuntimeError(f'TitlePrompt.{prompt_field_name} is empty')
    rendered_prompt = render_prompt_template(
        prompt_text,
        {
            'PROJECT_NAME': project.name,
            'CURRENT_STRUCTURE_JSON_OR_EMPTY_ARRAY': current_structure_text,
            'CURRENT_STRUCTURE_JSON': current_structure_text,
            'USER_MODIFICATION_REQUEST_OR_EMPTY': user_modification_request,
            'USER_MODIFICATION_REQUEST': user_modification_request,
            'OBSERVED_PAGES': observed_pages_text,
            'OBSERVED_PAGES_JSON': observed_pages_text,
        },
    )
    if 'area_role' not in prompt_text or 'is_adoption_recommendable' not in prompt_text:
        rendered_prompt = f'{rendered_prompt.rstrip()}{AREA_METADATA_PROMPT_GUIDANCE}'
    prompt_name = f"{prompt.name}:{prompt_field_name}"
    prompt_version = build_prompt_version(prompt)
    return rendered_prompt, prompt_name, prompt_version


def _extract_json_payload(content):
    if not content:
        raise ValueError('Empty AI response')

    stripped = content.strip()
    fenced_match = re.search(r'```(?:json)?\s*(\{.*\})\s*```', stripped, re.DOTALL)
    if fenced_match:
        stripped = fenced_match.group(1)

    return json.loads(stripped)


def _sanitize_ai_rules(payload):
    return _normalize_prompt_rules(payload.get('rules', []))


def _llm_log_excerpt(value, limit=20):
    flattened = ' '.join(str(value or '').split())
    return flattened[:limit]


def _resolve_page_naming_run_id(run):
    if isinstance(run, ProjectPageNamingRun):
        return run.id
    return getattr(run, 'id', run)


def _write_llm_usage_log(
    *,
    duration_ms,
    result,
    feature='',
    project=None,
    run=None,
    mode='',
    model_name='',
    prompt_name='',
    prompt_version='',
    error_message='',
):
    project_id = _resolve_project_id(project)
    run_id = _resolve_page_naming_run_id(run)
    if not project_id and isinstance(run, ProjectPageNamingRun):
        project_id = run.project_id

    try:
        LLMUsageLog.objects.create(
            feature=feature,
            project_id=project_id,
            page_naming_run_id=run_id,
            mode=mode or '',
            model_name=model_name or '',
            prompt_name=prompt_name or '',
            prompt_version=prompt_version or '',
            result=result,
            duration_ms=duration_ms,
            error_message=error_message or '',
        )
    except Exception:
        logger.exception('Failed to write LLM usage log')


def _log_llm_usage(
    started_at,
    prompt,
    content='',
    result='ok',
    feature='',
    project=None,
    run=None,
    mode='',
    model_name='',
    prompt_name='',
    prompt_version='',
):
    duration_ms = round((time.perf_counter() - started_at) * 1000)
    llm_usage_logger.log(
        logging.INFO if result == 'ok' else logging.ERROR,
        "timestamp=%s result=%s duration_ms=%s input20=%r output20=%r",
        timezone.now().isoformat(),
        result,
        duration_ms,
        _llm_log_excerpt(prompt),
        _llm_log_excerpt(content),
    )
    _write_llm_usage_log(
        duration_ms=duration_ms,
        result=result,
        feature=feature,
        project=project,
        run=run,
        mode=mode,
        model_name=model_name,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        error_message=content if result != 'ok' else '',
    )


def _create_chat_completion_with_usage_log(
    client,
    *,
    model,
    prompt,
    feature='',
    project=None,
    run=None,
    mode='',
    prompt_name='',
    prompt_version='',
):
    started_at = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            response_format={'type': 'json_object'},
            messages=[{'role': 'user', 'content': prompt}],
        )
        content = response.choices[0].message.content or '{}'
    except Exception as exc:
        _log_llm_usage(
            started_at,
            prompt,
            content=str(exc),
            result='error',
            feature=feature,
            project=project,
            run=run,
            mode=mode,
            model_name=model,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
        )
        raise

    _log_llm_usage(
        started_at,
        prompt,
        content=content,
        result='ok',
        feature=feature,
        project=project,
        run=run,
        mode=mode,
        model_name=model,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
    )
    return content


def generate_page_naming_rules(project, mode, urls, existing_rules=None, model_name=None, run=None, phase=None):
    api_key = get_openai_api_key_for_project(project)
    if not api_key:
        raise WorkspaceOpenAIKeyError('No usable OpenAI API key is configured for this workspace.')

    client = openai.OpenAI(api_key=api_key)
    prompt_config = get_active_title_prompt()
    phase = phase or getattr(run, 'phase', '') or _default_page_naming_phase_for_mode(mode)
    prompt, prompt_name, prompt_version = _build_prompt(
        mode,
        project,
        urls,
        existing_rules=existing_rules,
        prompt=prompt_config,
        phase=phase,
    )
    model_name = model_name or _get_page_naming_openai_model_name(mode, prompt=prompt_config, phase=phase)

    content = _create_chat_completion_with_usage_log(
        client,
        model=model_name,
        prompt=prompt,
        feature='page_naming',
        project=project,
        run=run,
        mode=mode,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
    )
    payload = _extract_json_payload(content)
    rules = _sanitize_ai_rules(payload)

    return {
        'prompt_name': prompt_name,
        'prompt_version': prompt_version,
        'rules': rules,
        'payload': payload,
    }


def replace_project_page_rules(project, rules, created_by):
    with transaction.atomic():
        ProjectPageRule.objects.filter(project=project, is_active=True).update(is_active=False)
        created_rules = ProjectPageRule.objects.bulk_create(
            [
                ProjectPageRule(
                    project=project,
                    pattern=entry['pattern'],
                    product_area=entry['page_group'],
                    product_area_short_name=entry['page_group_short_name'],
                    area_role=entry.get('area_role', 'unknown'),
                    is_adoption_recommendable=entry.get('is_adoption_recommendable', False),
                    page_name=entry['page_name'],
                    priority=entry['priority'],
                    created_by=created_by,
                    is_active=True,
                )
                for entry in rules
            ]
        )

    return list(created_rules)


def apply_rules_to_analytics_events(project, rules, since, batch_size=500):
    compiled_rules = compile_page_rules(rules)
    queryset = AnalyticsEvent.objects.filter(session__project=project, timestamp__gte=since)
    updates = []
    updated_count = 0

    for analytics_event in queryset.only('id', 'url', 'url_normalized', 'product_area', 'page_name', 'page_rule_id').iterator(chunk_size=batch_size):
        normalized_url = normalize_page_url_key(analytics_event.url_normalized or analytics_event.url)
        rule, product_area, page_name = resolve_page_rule_match(normalized_url, compiled_rules=compiled_rules)
        analytics_event.url_normalized = normalized_url
        analytics_event.product_area = product_area
        analytics_event.page_name = page_name or DEFAULT_PAGE_NAME
        analytics_event.page_rule_id = rule.id if rule else None
        updates.append(analytics_event)
        if len(updates) >= batch_size:
            AnalyticsEvent.objects.bulk_update(
                updates,
                ['url_normalized', 'product_area', 'page_name', 'page_rule'],
                batch_size=batch_size,
            )
            updated_count += len(updates)
            updates = []

    if updates:
        AnalyticsEvent.objects.bulk_update(
            updates,
            ['url_normalized', 'product_area', 'page_name', 'page_rule'],
            batch_size=batch_size,
        )
        updated_count += len(updates)

    return updated_count


@contextmanager
def project_page_naming_lock(project_id):
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [int(project_id)])
        acquired = bool(cursor.fetchone()[0])

    try:
        yield acquired
    finally:
        if acquired:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(%s)', [int(project_id)])


def _serialize_rules_for_snapshot(rules):
    return [
        {
            'id': rule.id,
            'pattern': rule.pattern,
            'page_group': normalize_product_area(rule.product_area, rule.page_name),
            'page_group_short_name': normalize_product_area_short_name(rule.product_area_short_name, rule.product_area),
            'area_role': getattr(rule, 'area_role', 'unknown') or 'unknown',
            'is_adoption_recommendable': bool(getattr(rule, 'is_adoption_recommendable', False)),
            'page_name': rule.page_name,
            'priority': rule.priority,
            'created_by': rule.created_by,
        }
        for rule in _sorted_rules(rules)
    ]


def _finalize_run(run, status, skip_reason='', error_message='', **extra_fields):
    run.status = status
    run.skip_reason = skip_reason
    run.error_message = error_message
    run.finished_at = timezone.now()

    for field_name, value in extra_fields.items():
        setattr(run, field_name, value)

    run.save()
    return run


def run_page_naming_for_project(project_id, mode):
    project = Project.active.get(pk=project_id)

    with project_page_naming_lock(project.id) as acquired:
        if not acquired:
            return None

        run = ProjectPageNamingRun.objects.create(
            project=project,
            mode=mode,
            phase=_default_page_naming_phase_for_mode(mode),
            status=ProjectPageNamingRunStatus.SKIPPED,
        )

        try:
            adapter = get_source_adapter(project)
            now = timezone.now()
            first_event_at = project.page_naming_first_event_at or adapter.first_event_at()
            ensure_project_first_event_at(project, first_event_at)

            metrics = calculate_new_url_metrics(adapter, now=now)
            run.new_urls_1h = metrics['new_urls_1h']
            run.new_urls_24h = metrics['new_urls_24h']
            run.unique_urls_total = adapter.unique_urls_total()
            run.events_1h = metrics['events_1h']
            run.save(update_fields=['new_urls_1h', 'new_urls_24h', 'unique_urls_total', 'events_1h'])

            if mode == ProjectPageNamingRunMode.HOURLY_TITLE_BACKFILL:
                if not project_uses_analytics(project):
                    return _finalize_run(
                        run,
                        ProjectPageNamingRunStatus.SKIPPED,
                        skip_reason='project_without_analytics',
                    )

                unresolved_urls = build_title_backfill_urls(project)
                run.input_urls_count = len(unresolved_urls)
                run.save(update_fields=['input_urls_count'])
                if not unresolved_urls:
                    return _finalize_run(
                        run,
                        ProjectPageNamingRunStatus.SKIPPED,
                        skip_reason='no_unresolved_urls',
                    )

                active_rules = get_active_page_rules(project)
                if not active_rules:
                    return _finalize_run(
                        run,
                        ProjectPageNamingRunStatus.SKIPPED,
                        skip_reason='no_active_rules',
                    )

                applied_titles = apply_rules_to_unresolved_analytics_events(project, active_rules)
                if not applied_titles:
                    return _finalize_run(
                        run,
                        ProjectPageNamingRunStatus.SKIPPED,
                        skip_reason='no_matching_rules',
                    )

                return _finalize_run(
                    run,
                    ProjectPageNamingRunStatus.SUCCESS,
                    output_rules_count=applied_titles,
                )

            if mode == ProjectPageNamingRunMode.HOURLY_UNSTABLE:
                if run.events_1h == 0:
                    return _finalize_run(
                        run,
                        ProjectPageNamingRunStatus.SKIPPED,
                        skip_reason='no_events_last_hour',
                    )

                if first_event_at:
                    project_age = now - first_event_at
                    # Low 24h URL churn is required for both stabilization paths.
                    if (
                        run.new_urls_24h <= get_stable_new_urls_threshold()
                        and (
                            project_age > get_stable_after_hard_window()
                            or (
                                project_age > get_stable_after_soft_window()
                                and run.unique_urls_total >= get_stable_min_unique_urls()
                            )
                        )
                    ):
                        set_project_page_naming_state(project, ProjectPageNamingState.STABLE)
                        return _finalize_run(
                            run,
                            ProjectPageNamingRunStatus.SKIPPED,
                            skip_reason='project_became_stable',
                        )

                if run.new_urls_1h == 0:
                    return _finalize_run(
                        run,
                        ProjectPageNamingRunStatus.SKIPPED,
                        skip_reason='no_new_urls_last_hour',
                    )

                urls = build_hybrid_urls(project, adapter, now=now)
                if not urls:
                    return _finalize_run(
                        run,
                        ProjectPageNamingRunStatus.SKIPPED,
                        skip_reason='no_urls_for_prompt',
                    )
                run.input_urls_count = len(urls)
                run.save(update_fields=['input_urls_count'])

                active_rules = get_active_page_rules(project)
                phase = resolve_hourly_unstable_page_naming_phase(project)
                if phase != ProjectPageNamingPhase.BOOTSTRAP and not sample_urls_need_rule_refresh(urls, active_rules):
                    return _finalize_run(
                        run,
                        ProjectPageNamingRunStatus.SKIPPED,
                        skip_reason='recent_urls_covered_by_active_rules',
                    )

                if run.phase != phase:
                    run.phase = phase
                    run.save(update_fields=['phase'])

                existing_rules = _serialize_rules_for_snapshot(active_rules)
                ai_result = generate_page_naming_rules(
                    project,
                    mode,
                    urls,
                    existing_rules=existing_rules,
                    run=run,
                    phase=phase,
                )
                if not ai_result['rules']:
                    return _finalize_run(
                        run,
                        ProjectPageNamingRunStatus.FAILED,
                        error_message='AI returned no valid rules',
                        prompt_name=ai_result['prompt_name'],
                        prompt_version=ai_result['prompt_version'],
                    )

                created_rules = replace_project_page_rules(
                    project,
                    ai_result['rules'],
                    ProjectPageNamingRunMode.HOURLY_UNSTABLE,
                )
                ProjectPageRuleVersion.objects.create(
                    project=project,
                    run=run,
                    mode=mode,
                    phase=phase,
                    rules_json=_serialize_rules_for_snapshot(created_rules),
                    ai_response_json=ai_result['payload'],
                )

                unstable_since = now - get_unstable_rewrite_window()
                if project_uses_analytics(project):
                    apply_rules_to_analytics_events(project, created_rules, unstable_since)

                return _finalize_run(
                    run,
                    ProjectPageNamingRunStatus.SUCCESS,
                    prompt_name=ai_result['prompt_name'],
                    prompt_version=ai_result['prompt_version'],
                    output_rules_count=len(created_rules),
                )

            stable_input_start = now - get_stable_input_window()
            if run.new_urls_24h > get_unstable_new_urls_threshold():
                set_project_page_naming_state(project, ProjectPageNamingState.NOT_STABLE)
                return _finalize_run(
                    run,
                    ProjectPageNamingRunStatus.SKIPPED,
                    skip_reason='project_became_not_stable',
                )

            urls = build_hybrid_urls(project, adapter, now=now, start_time=stable_input_start)
            if not urls:
                return _finalize_run(
                    run,
                    ProjectPageNamingRunStatus.SKIPPED,
                    skip_reason='no_urls_for_prompt',
                )
            run.input_urls_count = len(urls)
            run.save(update_fields=['input_urls_count'])

            active_rules = get_active_page_rules(project)
            if not sample_urls_need_rule_refresh(urls, active_rules):
                return _finalize_run(
                    run,
                    ProjectPageNamingRunStatus.SKIPPED,
                    skip_reason='recent_urls_covered_by_active_rules',
                )

            existing_rules = _serialize_rules_for_snapshot(active_rules)
            ai_result = generate_page_naming_rules(
                project,
                mode,
                urls,
                existing_rules=existing_rules,
                run=run,
                phase=ProjectPageNamingPhase.STABLE,
            )
            if not ai_result['rules']:
                return _finalize_run(
                    run,
                    ProjectPageNamingRunStatus.FAILED,
                    error_message='AI returned no valid rules',
                    prompt_name=ai_result['prompt_name'],
                    prompt_version=ai_result['prompt_version'],
                )

            created_rules = replace_project_page_rules(
                project,
                ai_result['rules'],
                ProjectPageNamingRunMode.DAILY_STABLE,
            )
            ProjectPageRuleVersion.objects.create(
                project=project,
                run=run,
                mode=mode,
                phase=ProjectPageNamingPhase.STABLE,
                rules_json=_serialize_rules_for_snapshot(created_rules),
                ai_response_json=ai_result['payload'],
            )

            if project_uses_analytics(project):
                apply_rules_to_analytics_events(project, created_rules, stable_input_start)

            return _finalize_run(
                run,
                ProjectPageNamingRunStatus.SUCCESS,
                prompt_name=ai_result['prompt_name'],
                prompt_version=ai_result['prompt_version'],
                output_rules_count=len(created_rules),
            )

        except WorkspaceOpenAIKeyError:
            return _finalize_run(
                run,
                ProjectPageNamingRunStatus.SKIPPED,
                skip_reason='workspace_openai_key_unavailable',
            )
        except OpenAIError as exc:
            logger.exception("OpenAI error during page naming run for project %s", project.id)
            return _finalize_run(run, ProjectPageNamingRunStatus.FAILED, error_message=str(exc))
        except Exception as exc:
            logger.exception("Unhandled page naming error for project %s", project.id)
            return _finalize_run(run, ProjectPageNamingRunStatus.FAILED, error_message=str(exc))
