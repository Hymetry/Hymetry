import re
from datetime import timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.text import slugify

from apps.pages.locks import project_advisory_lock
from apps.pages.models import (
    CompaniesDetailCache,
    CompaniesOverviewCache,
    PageDailyMetric,
    PagesDetailCache,
    PagesOverviewCache,
    PagesScatterTooltipCache,
    ProductArea,
    UsersDetailCache,
    UsersOverviewCache,
)
from apps.pages.product_area_colors import (
    VISITS_PRODUCT_AREA_COLOR_PALETTE,
    explicit_product_area_color,
)
from apps.projects.models import Project, ProjectPageNamingState
from apps.tracker.models import ProjectPageRule


NOT_STABLE_LOOKBACK_DAYS = 7
STABLE_LOOKBACK_DAYS = 30


COLOR_CACHE_MODELS = (
    ('pages_overview', PagesOverviewCache),
    ('pages_detail', PagesDetailCache),
    ('pages_scatter_tooltips', PagesScatterTooltipCache),
    ('companies_overview', CompaniesOverviewCache),
    ('companies_detail', CompaniesDetailCache),
    ('users_overview', UsersOverviewCache),
    ('users_detail', UsersDetailCache),
)


PRODUCT_AREA_SLUG_SEPARATOR_RE = re.compile(r'[\W_]+', flags=re.UNICODE)


def _project_timezone(timezone_name):
    try:
        return ZoneInfo(timezone_name or 'UTC')
    except ZoneInfoNotFoundError:
        return ZoneInfo('UTC')


def _assignment_window(project, lookback_days, as_of=None):
    current_time = as_of or timezone.now()
    if timezone.is_naive(current_time):
        current_time = current_time.replace(tzinfo=datetime_timezone.utc)
    end_date = current_time.astimezone(_project_timezone(project.timezone)).date()
    return end_date - timedelta(days=lookback_days - 1), end_date


def _visits_by_product_area(project_id, product_area_ids, start_date, end_date):
    if not product_area_ids:
        return {}

    rows = (
        PageDailyMetric.objects
        .filter(
            project_id=project_id,
            product_area_id__in=product_area_ids,
            date__gte=start_date,
            date__lte=end_date,
        )
        .values('product_area_id')
        .annotate(total_visits=Sum('visits_count'))
    )
    return {
        row['product_area_id']: int(row.get('total_visits') or 0)
        for row in rows
    }


def _canonical_product_area_slug(product_area_name):
    normalized_name = str(product_area_name or '').strip()
    if not normalized_name:
        return ''
    normalized_slug = PRODUCT_AREA_SLUG_SEPARATOR_RE.sub('-', normalized_name).strip('-').lower()
    return normalized_slug or 'unassigned'


def _current_product_areas(project_id):
    active_rules = list(
        ProjectPageRule.objects
        .select_for_update()
        .filter(project_id=project_id, is_active=True)
        .only('product_area')
    )
    current_names = {
        str(rule.product_area or '').strip()
        for rule in active_rules
        if str(rule.product_area or '').strip()
    }
    if not current_names:
        return []

    slug_candidates_by_name = {}
    candidate_slugs = set()
    for name in current_names:
        canonical_slug = _canonical_product_area_slug(name)
        legacy_slug = slugify(name) or 'unassigned'
        candidates = tuple(dict.fromkeys((canonical_slug, legacy_slug)))
        slug_candidates_by_name[name] = candidates
        candidate_slugs.update(candidates)

    product_areas_by_slug = {
        area.slug: area
        for area in (
            ProductArea.objects
            .select_for_update()
            .filter(project_id=project_id, slug__in=candidate_slugs)
            .order_by('id')
        )
    }
    current_areas_by_id = {}
    for name in current_names:
        area = next(
            (
                product_areas_by_slug.get(slug)
                for slug in slug_candidates_by_name[name]
                if product_areas_by_slug.get(slug) is not None
            ),
            None,
        )
        if area is not None:
            current_areas_by_id[area.id] = area

    return list(current_areas_by_id.values())


def _mark_product_area_color_caches_stale(project_id):
    updated = {
        cache_name: cache_model.objects.filter(project_id=project_id, is_stale=False).update(is_stale=True)
        for cache_name, cache_model in COLOR_CACHE_MODELS
    }
    return updated


def _assignment_policy(expected_state):
    if expected_state == ProjectPageNamingState.NOT_STABLE:
        return NOT_STABLE_LOOKBACK_DAYS, True
    if expected_state == ProjectPageNamingState.STABLE:
        return STABLE_LOOKBACK_DAYS, False
    raise ValueError(f'Unsupported page naming state: {expected_state}')


def assign_project_product_area_colors(project_id, expected_state, *, as_of=None):
    """Assign ranked colors to the canonical ProductArea rows for one active project.

    ProductArea has no active/current marker, so distinct nonblank product areas
    from active ProjectPageRule rows define the current set. The project, active
    rules, and matched ProductArea rows are locked so overlapping runs serialize.
    The shared pages-rebuild advisory lock also keeps color writes and cache stale
    marking atomic relative to analytics cache rebuilds.
    """

    lookback_days, overwrite_existing = _assignment_policy(expected_state)

    with project_advisory_lock(project_id, namespace='pages-rebuild') as acquired:
        if not acquired:
            return {
                'status': 'skipped',
                'reason': 'lock_not_acquired',
                'project_id': project_id,
                'page_naming_state': expected_state,
            }
        return _assign_project_product_area_colors_under_lock(
            project_id,
            expected_state,
            lookback_days=lookback_days,
            overwrite_existing=overwrite_existing,
            as_of=as_of,
        )


def _assign_project_product_area_colors_under_lock(
    project_id,
    expected_state,
    *,
    lookback_days,
    overwrite_existing,
    as_of=None,
):
    with transaction.atomic():
        project = (
            Project.active
            .select_for_update()
            .filter(pk=project_id, page_naming_state=expected_state)
            .first()
        )
        if project is None:
            return {
                'status': 'skipped',
                'reason': 'project_not_active_or_state_changed',
                'project_id': project_id,
                'page_naming_state': expected_state,
            }

        start_date, end_date = _assignment_window(project, lookback_days, as_of=as_of)
        product_areas = _current_product_areas(project.id)
        visits_by_area = _visits_by_product_area(
            project.id,
            [area.id for area in product_areas],
            start_date,
            end_date,
        )
        ranked_areas = sorted(
            product_areas,
            key=lambda area: (
                -visits_by_area.get(area.id, 0),
                (area.slug or '').casefold(),
                area.id,
            ),
        )

        changed_areas = []
        assignments = []
        changed_at = timezone.now()
        for index, area in enumerate(ranked_areas):
            desired_color = VISITS_PRODUCT_AREA_COLOR_PALETTE[
                index % len(VISITS_PRODUCT_AREA_COLOR_PALETTE)
            ]
            has_color = bool(explicit_product_area_color({'color': area.color}))
            should_assign = overwrite_existing or not has_color
            changed = should_assign and area.color != desired_color
            if changed:
                area.color = desired_color
                area.updated_at = changed_at
                changed_areas.append(area)

            assignments.append({
                'product_area_id': area.id,
                'slug': area.slug,
                'visits_count': visits_by_area.get(area.id, 0),
                'color': area.color,
                'changed': changed,
            })

        if changed_areas:
            ProductArea.objects.bulk_update(changed_areas, ['color', 'updated_at'])
            stale_cache_counts = _mark_product_area_color_caches_stale(project.id)
        else:
            stale_cache_counts = {cache_name: 0 for cache_name, _cache_model in COLOR_CACHE_MODELS}

    return {
        'status': 'success',
        'project_id': project.id,
        'page_naming_state': expected_state,
        'lookback_days': lookback_days,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'product_areas_count': len(ranked_areas),
        'updated_count': len(changed_areas),
        'stale_cache_counts': stale_cache_counts,
        'assignments': assignments,
    }


def assign_not_stable_project_product_area_colors(project_id, *, as_of=None):
    return assign_project_product_area_colors(
        project_id,
        ProjectPageNamingState.NOT_STABLE,
        as_of=as_of,
    )


def assign_stable_project_product_area_colors(project_id, *, as_of=None):
    return assign_project_product_area_colors(
        project_id,
        ProjectPageNamingState.STABLE,
        as_of=as_of,
    )
