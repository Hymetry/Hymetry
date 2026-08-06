"""Company segments: named, reusable company-attribute filter definitions.

A segment stores the same filter definition the dialog and the ``ca.*`` URL
state already use, so applying one is exactly the existing company-attribute
filter with a label attached. Segments are personal: they belong to one user
inside one project.

The one exception is the *seeded* segment, which has no owner and belongs to
the project itself. The read-only demo is served to anonymous visitors, so it
offers seeded segments — listed and applied, never created, renamed, edited, or
deleted — while personal segments stay invisible there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from django.db import IntegrityError, transaction
from django.db.models.functions import Lower
from django.urls import reverse

from .company_attribute_filters import (
    CompanyAttributeFilterState,
    CompanyAttributeFilterValidationError,
    filter_state_from_definition,
    parse_company_attribute_filters,
    resolve_company_cohorts,
)
from .company_segment_reviews import (
    clear_segment_review_if_resolved,
    review_notice,
    serialize_deletion_records,
)
from .models import CompanySegment
from .url_helpers import project_route


SEGMENT_NAME_MAX_LENGTH = 100
MAX_SEGMENTS_PER_USER = 100
SEGMENT_QUERY_PARAMETER = 'segment'
SEGMENT_ID_PLACEHOLDER = '__segment_id__'


def company_segment_urls(project) -> dict[str, str]:
    """Client-side URL templates for the segment endpoints."""

    return {
        'list': project_route(project, 'project_company_segments'),
        'create': project_route(project, 'create_project_company_segment'),
        'update': project_route(
            project,
            'update_project_company_segment',
            segment_id=SEGMENT_ID_PLACEHOLDER,
        ),
        'delete': project_route(
            project,
            'delete_project_company_segment',
            segment_id=SEGMENT_ID_PLACEHOLDER,
        ),
    }


def demo_company_segment_urls() -> dict[str, str]:
    """Only the list endpoint: the demo's seeded segments are read-only."""

    return {'list': reverse('demo_company_segments')}


class CompanySegmentValidationError(Exception):
    """A JSON-safe set of field errors for one segment mutation."""

    def __init__(self, errors):
        self.errors = errors or {'_payload': ['The request could not be validated.']}
        super().__init__('Company segment validation failed.')


class CompanySegmentNotFound(Exception):
    """Raised when a segment id does not resolve inside the caller's scope."""


@dataclass(frozen=True)
class CompanyScope:
    """The company scope one analytics request runs under.

    ``blocked_segment`` is a segment the request asked for and the server
    refused to apply because it still references a deleted attribute. Nothing
    from it reaches ``state``: applying what is left of such a definition would
    quietly answer a different question than the one the segment names.
    """

    state: CompanyAttributeFilterState
    segment: CompanySegment | None = None
    segments_enabled: bool = False
    segments_manageable: bool = False
    blocked_segment: CompanySegment | None = None
    review_notice: dict[str, Any] | None = None

    @property
    def type(self) -> str:
        if self.segment is not None:
            return 'segment'
        return 'custom' if self.state.active else 'all'

    @property
    def label(self) -> str:
        if self.segment is not None:
            return self.segment.name
        return 'Custom filter' if self.state.active else 'All companies'

    @property
    def segment_id(self) -> str:
        return str(self.segment.id) if self.segment is not None else ''

    @property
    def blocked_segment_id(self) -> str:
        return str(self.blocked_segment.id) if self.blocked_segment is not None else ''

    @property
    def url_segment_id(self) -> str:
        """The ``segment`` parameter the canonical URL keeps.

        A blocked segment keeps its id in the URL even though it filters
        nothing, so a reload or a shared link still explains why the page shows
        every company instead of the segment's cohort.
        """

        return self.segment_id or self.blocked_segment_id

    @property
    def canonical_pairs(self) -> tuple[tuple[str, str], ...]:
        pairs = self.state.canonical_pairs
        if self.segment is None:
            return pairs
        return ((SEGMENT_QUERY_PARAMETER, self.segment_id),) + pairs

    def to_payload(self) -> dict[str, Any]:
        return {
            'type': self.type,
            'label': self.label,
            'segmentId': self.segment_id,
            'segmentName': self.segment.name if self.segment is not None else '',
            'activeCount': self.state.active_count,
            'blockedSegmentId': self.blocked_segment_id,
            'blockedSegmentName': (
                self.blocked_segment.name if self.blocked_segment is not None else ''
            ),
        }


def segment_queryset(project, user):
    if not getattr(user, 'is_authenticated', False):
        return CompanySegment.objects.none()
    return CompanySegment.objects.filter(project=project, user=user)


def seeded_segment_queryset(project):
    """The project's ownerless segments, which only the demo surfaces."""

    return CompanySegment.objects.filter(project=project, user__isnull=True)


def _ordered(queryset) -> list[CompanySegment]:
    return list(queryset.order_by(Lower('name'), 'id'))


def _by_id(queryset, segment_id) -> CompanySegment:
    value = str(segment_id or '').strip()
    if not value.isdigit():
        raise CompanySegmentNotFound('That company segment no longer exists.')
    segment = queryset.filter(pk=int(value)).first()
    if segment is None:
        raise CompanySegmentNotFound('That company segment no longer exists.')
    return segment


def list_company_segments(project, user) -> list[CompanySegment]:
    return _ordered(segment_queryset(project, user))


def list_seeded_company_segments(project) -> list[CompanySegment]:
    return _ordered(seeded_segment_queryset(project))


def get_company_segment(project, user, segment_id) -> CompanySegment:
    return _by_id(segment_queryset(project, user), segment_id)


def get_seeded_company_segment(project, segment_id) -> CompanySegment:
    return _by_id(seeded_segment_queryset(project), segment_id)


def segment_filter_state(
    project,
    segment: CompanySegment,
    *,
    attributes: Iterable[Any] | None = None,
) -> CompanyAttributeFilterState:
    """Parse a stored definition leniently so deleted attributes just drop out."""

    return filter_state_from_definition(
        project,
        segment.definition,
        attributes=attributes,
    )


def normalize_segment_definition(
    project,
    raw_definition: Any,
    *,
    attributes: Iterable[Any] | None = None,
    field: str = 'definition',
) -> dict[str, Any]:
    """Validate a submitted definition and return its canonical stored form."""

    if not isinstance(raw_definition, Mapping):
        raise CompanySegmentValidationError({field: ['Send a company attribute filter definition.']})
    try:
        state = filter_state_from_definition(
            project,
            raw_definition,
            strict=True,
            attributes=attributes,
        )
    except CompanyAttributeFilterValidationError as exc:
        raise CompanySegmentValidationError({
            field: [issue.message for issue in exc.issues] or ['Check the filter conditions.'],
        }) from exc
    if not state.active:
        raise CompanySegmentValidationError({
            field: ['Add at least one company attribute condition.'],
        })
    return state.applied


def normalize_segment_name(project, user, raw_name: Any, *, exclude: CompanySegment | None = None) -> str:
    name = str(raw_name or '').strip()
    if not name:
        raise CompanySegmentValidationError({'name': ['Enter a segment name.']})
    if len(name) > SEGMENT_NAME_MAX_LENGTH:
        raise CompanySegmentValidationError({
            'name': [f'Use {SEGMENT_NAME_MAX_LENGTH} characters or fewer.'],
        })
    duplicates = segment_queryset(project, user).filter(name__iexact=name)
    if exclude is not None:
        duplicates = duplicates.exclude(pk=exclude.pk)
    if duplicates.exists():
        raise CompanySegmentValidationError({
            'name': ['You already have a company segment with this name.'],
        })
    return name


def create_company_segment(project, user, raw_name: Any, raw_definition: Any) -> CompanySegment:
    definition = normalize_segment_definition(project, raw_definition)
    name = normalize_segment_name(project, user, raw_name)
    if segment_queryset(project, user).count() >= MAX_SEGMENTS_PER_USER:
        raise CompanySegmentValidationError({
            'name': [f'You can save up to {MAX_SEGMENTS_PER_USER} company segments.'],
        })
    segment = CompanySegment(project=project, user=user, name=name, definition=definition)
    _save_segment(segment)
    return segment


def rename_company_segment(project, user, segment: CompanySegment, raw_name: Any) -> CompanySegment:
    name = normalize_segment_name(project, user, raw_name, exclude=segment)
    if name == segment.name:
        return segment
    segment.name = name
    _save_segment(segment, update_fields=['name', 'updated_at'])
    return segment


def update_company_segment_definition(
    project,
    segment: CompanySegment,
    raw_definition: Any,
) -> CompanySegment:
    """Store a validated definition and retire the review flag once it is clean.

    Strict validation already refuses a definition that names an attribute the
    project no longer has, so a saved definition normally clears the flag on its
    own. The check is made against the stored definition anyway, so the flag is
    decided by what is written rather than by having opened the editor.
    """

    segment.definition = normalize_segment_definition(project, raw_definition)
    _save_segment(segment, update_fields=['definition', 'updated_at'])
    clear_segment_review_if_resolved(segment)
    return segment


def delete_company_segment(segment: CompanySegment) -> None:
    segment.delete()


def _save_segment(segment: CompanySegment, *, update_fields=None) -> None:
    try:
        with transaction.atomic():
            segment.save(update_fields=update_fields)
    except IntegrityError as exc:
        # The case-insensitive unique constraint is the authority; a concurrent
        # save can still land between the pre-check and this write.
        raise CompanySegmentValidationError({
            'name': ['You already have a company segment with this name.'],
        }) from exc


def company_segment_match_counts(
    project,
    segments: Iterable[CompanySegment],
    observed_company_ids: Iterable[str],
    *,
    attributes: Iterable[Any] | None = None,
) -> dict[int, int]:
    """Count matching companies for several segments with shared lookups."""

    segments = list(segments)
    if not segments:
        return {}
    states = [
        segment_filter_state(project, segment, attributes=attributes)
        for segment in segments
    ]
    cohorts = resolve_company_cohorts(states, observed_company_ids)
    return {
        segment.id: len(cohort)
        for segment, cohort in zip(segments, cohorts)
    }


def serialize_company_segment(
    segment: CompanySegment,
    *,
    state: CompanyAttributeFilterState | None = None,
    matching_count: int | None = None,
    project_timezone: Any = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        'id': str(segment.id),
        'name': segment.name,
        'definition': segment.definition if isinstance(segment.definition, dict) else {},
        'updatedAt': segment.updated_at.isoformat() if segment.updated_at else '',
        'needsReview': bool(segment.needs_review),
        # The name stays exactly as its owner wrote it; the warning travels
        # beside it so the UI can mark the segment without renaming it.
        'deletedAttributes': (
            serialize_deletion_records(segment, project_timezone or 'UTC')
            if segment.needs_review
            else []
        ),
    }
    if state is not None:
        payload['canonicalPairs'] = [list(pair) for pair in state.canonical_pairs]
        payload['summaries'] = list(state.summaries)
        payload['activeCount'] = state.active_count
    if matching_count is not None:
        payload['matchingCompanyCount'] = matching_count
    return payload


def resolve_company_scope(
    request,
    project,
    *,
    attributes: Iterable[Any] | None = None,
    is_demo_view: bool = False,
) -> CompanyScope:
    """
    Resolve the active company scope for one analytics request.

    A valid ``segment`` parameter is authoritative: its stored definition wins
    over any ``ca.*`` pairs in the URL, and
    ``canonical_company_scope_redirect`` rewrites the URL when the two disagree.
    Anything else is the existing URL-driven filter, either empty (All
    companies) or an unsaved custom filter.

    A segment marked ``needs_review`` is refused rather than approximated. Its
    own conditions are dropped *and* so are the URL's, because those pairs are
    what the client sends alongside ``segment=<id>``; keeping them would apply
    the very partial cohort the review exists to prevent.

    The demo resolves ``segment`` against the project's seeded segments instead
    of the visitor, who is usually anonymous and never owns anything there.
    """

    if is_demo_view:
        segments_enabled = True
        segments_manageable = False
    else:
        segments_enabled = bool(getattr(request.user, 'is_authenticated', False))
        segments_manageable = segments_enabled

    notice = (
        review_notice(project, request.user)
        if segments_enabled and not is_demo_view
        else None
    )

    segment = None
    if segments_enabled:
        raw_segment_id = str(request.GET.get(SEGMENT_QUERY_PARAMETER) or '').strip()
        if raw_segment_id:
            try:
                segment = (
                    get_seeded_company_segment(project, raw_segment_id)
                    if is_demo_view
                    else get_company_segment(project, request.user, raw_segment_id)
                )
            except CompanySegmentNotFound:
                segment = None

    if segment is not None and segment.needs_review:
        return CompanyScope(
            state=parse_company_attribute_filters(project, {}, attributes=attributes),
            segment=None,
            segments_enabled=segments_enabled,
            segments_manageable=segments_manageable,
            blocked_segment=segment,
            review_notice=notice,
        )

    if segment is not None:
        state = segment_filter_state(project, segment, attributes=attributes)
        if state.active:
            return CompanyScope(
                state=state,
                segment=segment,
                segments_enabled=True,
                segments_manageable=segments_manageable,
                review_notice=notice,
            )
        # Every referenced attribute is gone; fall back to the URL state so the
        # page still renders instead of silently applying nothing under a label.
        segment = None

    state = parse_company_attribute_filters(project, request.GET, attributes=attributes)
    return CompanyScope(
        state=state,
        segment=None,
        segments_enabled=segments_enabled,
        segments_manageable=segments_manageable,
        review_notice=notice,
    )


__all__ = [
    'MAX_SEGMENTS_PER_USER',
    'SEGMENT_ID_PLACEHOLDER',
    'SEGMENT_NAME_MAX_LENGTH',
    'SEGMENT_QUERY_PARAMETER',
    'CompanyScope',
    'CompanySegmentNotFound',
    'CompanySegmentValidationError',
    'company_segment_match_counts',
    'company_segment_urls',
    'create_company_segment',
    'delete_company_segment',
    'demo_company_segment_urls',
    'get_company_segment',
    'get_seeded_company_segment',
    'list_company_segments',
    'list_seeded_company_segments',
    'normalize_segment_definition',
    'normalize_segment_name',
    'rename_company_segment',
    'resolve_company_scope',
    'seeded_segment_queryset',
    'segment_filter_state',
    'segment_queryset',
    'serialize_company_segment',
    'update_company_segment_definition',
]
