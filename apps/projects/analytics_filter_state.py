"""Per-user filter state for the analytical pages: what each person last applied.

Two kinds of state are remembered, and they are deliberately separate.

Some filters answer a question about the project rather than about a screen.
"Which companies am I looking at" and "over what period" mean the same thing on
Pages, Companies, Users, and Visits, so the company-attribute scope and the
selected period are stored once per user and project and restored on all of
them.

Everything else belongs to the page it lives on. A Visits page filter means
nothing on Companies and a Pages product-area filter means nothing on Users, so
page filters are stored under a stable page key and are never copied from one
page to another.

Restoring happens by redirecting to the URL the stored state describes, which
keeps one rule true everywhere: the address bar states the filters the page is
answering with. That is what lets an explicit URL win over stored state — a
request that already names any of the page's filter parameters is taken at its
word, including when it names none of the company-attribute ones, because that
is what clearing a filter looks like.

Only committed state is stored. A value is written after the page resolved and
applied it, never while a dialog is still being edited, so drafts and transient
table state (search, sort, pagination) stay out. Stored values are stable IDs in
the existing filter-definition format, never labels, and a value whose target no
longer exists is dropped when the state is read.

The demo project is excluded from all of this. It is one shared, read-only
project served to anonymous visitors, so there is nobody to remember anything
for; demo requests read and write nothing here and keep using defaults or the
parameters their URL carries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from django.db import IntegrityError, transaction
from django.shortcuts import redirect
from django.utils import timezone

from .company_attribute_filters import filter_state_from_definition
from .company_segments import SEGMENT_QUERY_PARAMETER, segment_filter_state
from .demo import is_demo_project
from .models import AnalyticsFilterState, AnalyticsPageState


PAGES_OVERVIEW = 'pages_overview'
COMPANIES_OVERVIEW = 'companies_overview'
USERS_OVERVIEW = 'users_overview'
VISITS = 'visits'

# Every analytical surface offers the same four periods and normalizes an
# unknown one to 30 days on its own. This bound only decides what may be handed
# back to a page, so a period that was retired stops being restored instead of
# being rewritten by the view on every request.
ANALYTICS_RANGE_KEYS = frozenset({
    'last_7_days',
    'last_30_days',
    'last_90_days',
    'last_180_days',
})
DEFAULT_RANGE_KEY = 'last_30_days'

# Parameters that belong to the project rather than to a page. Every page reads
# the period from the same parameter and means the same thing by it, so moving
# between pages keeps the window somebody chose instead of resetting it.
PROJECT_LEVEL_PARAMETERS = frozenset({'range'})

# Product-area filter keys are Product Area slugs, plus the two keys the
# analytics payloads use for pages that belong to no area.
UNASSIGNED_PRODUCT_AREA_KEYS = frozenset({'unassigned', 'unclassified'})

MAX_STORED_VALUES_PER_PARAMETER = 50
MAX_STORED_VALUE_LENGTH = 200

StoredState = dict[str, list[str]]


@dataclass(frozen=True)
class PageStateSpec:
    """What one page may state in its URL, and what may be remembered for it.

    ``url_parameters`` is the wider set: every parameter whose presence means
    the request is stating this page's filters, including the transient table
    parameters that are read but never stored. ``stored_parameters`` is what may
    actually be written and handed back, whichever row it ends up in.
    """

    key: str
    url_parameters: frozenset[str]
    stored_parameters: tuple[str, ...]
    choices: Mapping[str, frozenset[str]] = field(default_factory=dict)
    defaults: Mapping[str, str] = field(default_factory=dict)
    sanitize: Callable[[Any, StoredState], StoredState] | None = None

    @property
    def project_level_parameters(self) -> tuple[str, ...]:
        return tuple(
            name for name in self.stored_parameters
            if name in PROJECT_LEVEL_PARAMETERS
        )

    @property
    def page_level_parameters(self) -> tuple[str, ...]:
        return tuple(
            name for name in self.stored_parameters
            if name not in PROJECT_LEVEL_PARAMETERS
        )


def _sanitize_pages_overview_state(project, values: StoredState) -> StoredState:
    """Drop product areas the project no longer has."""

    requested = values.get('product_area')
    if not requested:
        return values

    from apps.pages.models import ProductArea

    known = {
        slug.strip().lower()
        for slug in ProductArea.objects
        .filter(project=project)
        .values_list('slug', flat=True)
        if slug
    } | UNASSIGNED_PRODUCT_AREA_KEYS
    kept = [key for key in requested if key.strip().lower() in known]
    sanitized = dict(values)
    if kept:
        sanitized['product_area'] = kept
    else:
        sanitized.pop('product_area', None)
    return sanitized


def _sanitize_visits_state(project, values: StoredState) -> StoredState:
    """Drop a page, product area, or identity Visits can no longer filter by."""

    from apps.tracker.visits_filters import (
        resolve_visits_page_filter,
        visits_entity_is_known,
        visits_page_filter_groups,
    )

    sanitized = dict(values)
    range_key = _single(sanitized.get('range')) or DEFAULT_RANGE_KEY

    page_filter_type = _single(sanitized.get('page_filter_type'))
    page_filter_id = _single(sanitized.get('page_filter_id'))
    if page_filter_type or page_filter_id:
        selection = resolve_visits_page_filter(
            visits_page_filter_groups(project),
            page_filter_type,
            page_filter_id,
        )
        if selection['type'] and selection['id']:
            sanitized['page_filter_type'] = [selection['type']]
            sanitized['page_filter_id'] = [selection['id']]
        else:
            sanitized.pop('page_filter_type', None)
            sanitized.pop('page_filter_id', None)

    entity_type = _single(sanitized.get('entity_type'))
    entity_id = _single(sanitized.get('entity_id'))
    if entity_type or entity_id:
        # ``None`` means the prepared overview the options come from has not
        # been built yet, which is not evidence that the identity is gone.
        if visits_entity_is_known(project, entity_type, entity_id, range_key=range_key) is False:
            sanitized.pop('entity_type', None)
            sanitized.pop('entity_id', None)
    return sanitized


PAGE_STATE_SPECS: dict[str, PageStateSpec] = {
    PAGES_OVERVIEW: PageStateSpec(
        key=PAGES_OVERVIEW,
        url_parameters=frozenset({'range', 'product_area', 'q', 'sort', 'direction', 'page'}),
        stored_parameters=('range', 'product_area'),
        choices={'range': ANALYTICS_RANGE_KEYS},
        defaults={'range': DEFAULT_RANGE_KEY},
        sanitize=_sanitize_pages_overview_state,
    ),
    COMPANIES_OVERVIEW: PageStateSpec(
        key=COMPANIES_OVERVIEW,
        url_parameters=frozenset({'range', 'period'}),
        stored_parameters=('range',),
        choices={'range': ANALYTICS_RANGE_KEYS},
        defaults={'range': DEFAULT_RANGE_KEY},
    ),
    USERS_OVERVIEW: PageStateSpec(
        key=USERS_OVERVIEW,
        url_parameters=frozenset({'range', 'period'}),
        stored_parameters=('range',),
        choices={'range': ANALYTICS_RANGE_KEYS},
        defaults={'range': DEFAULT_RANGE_KEY},
    ),
    VISITS: PageStateSpec(
        key=VISITS,
        url_parameters=frozenset({
            'range',
            'sort',
            'direction',
            'page',
            'entity_type',
            'entity_id',
            'page_filter_type',
            'page_filter_id',
        }),
        stored_parameters=(
            'range',
            'entity_type',
            'entity_id',
            'page_filter_type',
            'page_filter_id',
        ),
        choices={
            'range': ANALYTICS_RANGE_KEYS,
            'entity_type': frozenset({'company', 'user'}),
            'page_filter_type': frozenset({'area', 'page'}),
        },
        defaults={'range': DEFAULT_RANGE_KEY},
        sanitize=_sanitize_visits_state,
    ),
}


def restore_redirect(request, project, page_key, *, is_demo_view=False):
    """Send the request to the URL the person's stored filter state describes.

    Returns ``None`` when there is nothing to do: a request that already names
    any of the page's filter parameters is authoritative, and so is every demo
    or anonymous request.

    The redirect also spells out the page's defaults, so the URL a page is read
    from always states its own filters. Clearing a filter then produces a URL
    that still names the page, which is how a deliberate "show everything" stays
    distinguishable from arriving with nothing in particular in mind.
    """

    if request.method not in ('GET', 'HEAD'):
        return None
    if not persistence_enabled(request, project, is_demo_view=is_demo_view):
        return None

    spec = PAGE_STATE_SPECS[page_key]
    if url_states_page_filters(request, spec):
        return None

    query = request.GET.copy()
    for name, values in restored_page_parameters(project, request.user, spec).items():
        query.setlist(name, values)
    if not url_states_company_scope(request):
        for name, value in restored_company_parameters(project, request.user):
            query.appendlist(name, value)

    encoded = query.urlencode()
    if encoded == request.GET.urlencode():
        return None
    return redirect(f'{request.path}?{encoded}' if encoded else request.path)


def remember(request, project, page_key, *, scope=None, page_values=None, is_demo_view=False):
    """Store what the page just applied, so the next visit can restore it.

    Callers pass the values the page resolved rather than the ones it was sent,
    which is what keeps a filter naming something deleted from being written
    back, and what keeps a rejected draft out of the database entirely.
    """

    if not persistence_enabled(request, project, is_demo_view=is_demo_view):
        return
    spec = PAGE_STATE_SPECS[page_key]
    page_values = page_values or {}
    _remember_page_state(project, request.user, spec, page_values)
    _remember_project_state(project, request.user, spec, scope, page_values)


def persistence_enabled(request, project, *, is_demo_view=False):
    if is_demo_view or is_demo_project(project):
        return False
    return bool(getattr(getattr(request, 'user', None), 'is_authenticated', False))


def url_states_page_filters(request, spec: PageStateSpec) -> bool:
    return any(str(key) in spec.url_parameters for key in request.GET.keys())


def url_states_company_scope(request) -> bool:
    return any(
        str(key).startswith('ca.') or str(key) == SEGMENT_QUERY_PARAMETER
        for key in request.GET.keys()
    )


def restored_page_parameters(project, user, spec: PageStateSpec) -> StoredState:
    """The page parameters a restored URL should carry, defaults included.

    The project-level values come from the row every page shares, so the period
    somebody chose on one screen is the period the next screen opens with.
    """

    restored: StoredState = {
        name: [value]
        for name, value in spec.defaults.items()
        if name in spec.stored_parameters
    }
    restored.update(stored_project_state(project, user, spec))
    restored.update(stored_page_state(project, user, spec))
    # Sanitizing runs on the whole picture, because a page filter can only be
    # judged against the period it was applied under.
    if spec.sanitize is not None:
        restored = normalize_page_state(spec.sanitize(project, restored), spec)
    return restored


def stored_project_state(project, user, spec: PageStateSpec) -> StoredState:
    if not spec.project_level_parameters:
        return {}
    row = AnalyticsFilterState.objects.filter(project=project, user=user).first()
    if row is None:
        return {}
    return normalize_page_state(row.state, spec, names=spec.project_level_parameters)


def stored_page_state(project, user, spec: PageStateSpec) -> StoredState:
    if not spec.page_level_parameters:
        return {}
    row = (
        AnalyticsPageState.objects
        .filter(project=project, user=user, page_key=spec.key)
        .first()
    )
    if row is None:
        return {}
    return normalize_page_state(row.state, spec, names=spec.page_level_parameters)


def normalize_page_state(raw, spec: PageStateSpec, *, names=None) -> StoredState:
    """Keep only the parameters, shapes, and choices this page can act on."""

    values: StoredState = {}
    if not isinstance(raw, Mapping):
        return values
    for name in (spec.stored_parameters if names is None else names):
        allowed = spec.choices.get(name)
        cleaned = []
        for item in _as_list(raw.get(name)):
            if isinstance(item, bool) or not isinstance(item, (str, int)):
                continue
            text = str(item).strip()
            if not text or len(text) > MAX_STORED_VALUE_LENGTH:
                continue
            if allowed is not None and text not in allowed:
                continue
            if text not in cleaned:
                cleaned.append(text)
            if len(cleaned) >= MAX_STORED_VALUES_PER_PARAMETER:
                break
        if cleaned:
            values[name] = cleaned
    return values


def restored_company_parameters(project, user) -> tuple[tuple[str, str], ...]:
    """The ``ca.*``/``segment`` pairs a restored URL should carry.

    Parsing the stored definition against the project's current attributes is
    what drops conditions naming an attribute or option somebody deleted, and
    the pairs come back canonical so the page's own canonicalizing redirect has
    nothing left to correct.
    """

    row = (
        AnalyticsFilterState.objects
        .filter(project=project, user=user)
        .select_related('segment')
        .first()
    )
    if row is None:
        return ()

    segment = row.segment
    if segment is not None and segment.project_id == project.pk and segment.user_id == user.pk:
        segment_pair = (SEGMENT_QUERY_PARAMETER, str(segment.id))
        if segment.needs_review:
            # The page refuses to apply this one and says why; the id has to
            # survive for it to have anything to say.
            return (segment_pair,)
        state = segment_filter_state(project, segment)
        if state.active:
            return (segment_pair,) + state.canonical_pairs
        # Every attribute the segment named is gone, so the label would stand
        # for no conditions at all. Fall back to whatever the definition still
        # resolves to, exactly as an unsaved filter would.

    definition = row.definition if isinstance(row.definition, dict) else {}
    return filter_state_from_definition(project, definition).canonical_pairs


def _remember_page_state(project, user, spec: PageStateSpec, page_values) -> None:
    values = normalize_page_state(page_values, spec, names=spec.page_level_parameters)
    row = (
        AnalyticsPageState.objects
        .filter(project=project, user=user, page_key=spec.key)
        .first()
    )
    if row is None:
        if not values:
            return
        _create_or_update(
            lambda: AnalyticsPageState.objects.create(
                project=project,
                user=user,
                page_key=spec.key,
                state=values,
            ),
            lambda: AnalyticsPageState.objects
            .filter(project=project, user=user, page_key=spec.key)
            .update(state=values, updated_at=timezone.now()),
        )
        return
    if row.state != values:
        row.state = values
        row.save(update_fields=['state', 'updated_at'])


def _remember_project_state(project, user, spec: PageStateSpec, scope, page_values) -> None:
    """Write the one row every analytical page in this project shares.

    The company scope and the project-level page values live together because
    they are decided together: one render is one committed answer to both, and
    writing them as one row keeps a page from ever showing a period from this
    request beside a cohort from the last one.
    """

    values = normalize_page_state(page_values, spec, names=spec.project_level_parameters)
    row = AnalyticsFilterState.objects.filter(project=project, user=user).first()

    if scope is None:
        definition = row.definition if row is not None else {}
        segment_id = row.segment_id if row is not None else None
    else:
        definition = scope.state.applied
        # A segment the page refused to apply is still the scope the person
        # chose, and the page keeps its id in the URL to explain the refusal, so
        # that is what gets remembered.
        segment = scope.segment or scope.blocked_segment
        segment_id = segment.id if segment is not None else None

    if row is None:
        if not definition and segment_id is None and not values:
            return
        _create_or_update(
            lambda: AnalyticsFilterState.objects.create(
                project=project,
                user=user,
                definition=definition,
                segment_id=segment_id,
                state=values,
            ),
            lambda: AnalyticsFilterState.objects
            .filter(project=project, user=user)
            .update(
                definition=definition,
                segment_id=segment_id,
                state=values,
                updated_at=timezone.now(),
            ),
        )
        return
    if (
        row.definition != definition
        or row.segment_id != segment_id
        or row.state != values
    ):
        row.definition = definition
        row.segment_id = segment_id
        row.state = values
        row.save(update_fields=['definition', 'segment', 'state', 'updated_at'])


def _create_or_update(create, update) -> None:
    """Write the first row, or update the one another tab wrote first.

    Two screens opened at once resolve the same person's state independently, so
    the uniqueness constraint is what decides which of them inserts.
    """

    try:
        with transaction.atomic():
            create()
    except IntegrityError:
        update()


def _as_list(value):
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return value
    return (value,)


def _single(values):
    return values[0] if values else ''


__all__ = [
    'ANALYTICS_RANGE_KEYS',
    'COMPANIES_OVERVIEW',
    'DEFAULT_RANGE_KEY',
    'PAGES_OVERVIEW',
    'PAGE_STATE_SPECS',
    'PROJECT_LEVEL_PARAMETERS',
    'USERS_OVERVIEW',
    'VISITS',
    'PageStateSpec',
    'normalize_page_state',
    'persistence_enabled',
    'remember',
    'restore_redirect',
    'restored_company_parameters',
    'restored_page_parameters',
    'stored_page_state',
    'stored_project_state',
    'url_states_company_scope',
    'url_states_page_filters',
]
