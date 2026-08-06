from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .access import get_accessible_project_or_404
from .company_attribute_filter_views import SUPPORTED_SURFACES, overview_visit_queryset
from .company_attribute_filters import load_company_attribute_filter_attributes
from .company_segments import (
    SEGMENT_NAME_MAX_LENGTH,
    CompanySegmentNotFound,
    CompanySegmentValidationError,
    company_segment_match_counts,
    create_company_segment,
    delete_company_segment,
    get_company_segment,
    list_company_segments,
    list_seeded_company_segments,
    rename_company_segment,
    segment_filter_state,
    serialize_company_segment,
    update_company_segment_definition,
)
from .decorators import require_project_member
from .demo import get_demo_project


COMPANY_SEGMENT_MAX_REQUEST_BYTES = 100_000


def _json_payload(request):
    if len(request.body) > COMPANY_SEGMENT_MAX_REQUEST_BYTES:
        raise CompanySegmentValidationError({'_payload': ['The request is too large.']})
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompanySegmentValidationError({'_payload': ['Enter valid JSON.']}) from exc
    if not isinstance(payload, dict):
        raise CompanySegmentValidationError({'_payload': ['The JSON payload must be an object.']})
    return payload


def _validation_response(exc):
    return JsonResponse({'ok': False, 'errors': exc.errors}, status=400)


def _not_found_response(exc):
    return JsonResponse({'ok': False, 'errors': {'_payload': [str(exc)]}}, status=404)


def _observed_company_ids(request, project, surface):
    if surface == 'visits':
        from apps.tracker.visits_table import company_attribute_scope_company_ids

        return company_attribute_scope_company_ids(project, request)
    return (
        overview_visit_queryset(request, project, surface)
        .filter(company_id__isnull=False)
        .exclude(company_id='')
        .order_by()
        .values_list('company_id', flat=True)
        .distinct()
    )


def _surface(request):
    surface = str(request.GET.get('surface') or '').strip().lower()
    return surface if surface in SUPPORTED_SURFACES else 'companies'


def _segment_list_response(request, project, *, status=200, extra=None, segments=None):
    attributes = load_company_attribute_filter_attributes(project)
    if segments is None:
        segments = list_company_segments(project, request.user)
    # A segment awaiting review is counted for nothing: the only cohort still
    # derivable from it is the partial one the review exists to refuse, and a
    # number beside its name would read as an answer.
    countable = [segment for segment in segments if not segment.needs_review]
    counts = company_segment_match_counts(
        project,
        countable,
        _observed_company_ids(request, project, _surface(request)),
        attributes=attributes,
    )
    payload = {
        'ok': True,
        'segments': [
            serialize_company_segment(
                segment,
                state=segment_filter_state(project, segment, attributes=attributes),
                matching_count=None if segment.needs_review else counts.get(segment.id, 0),
                project_timezone=project.timezone,
            )
            for segment in segments
        ],
        'nameMaxLength': SEGMENT_NAME_MAX_LENGTH,
    }
    payload.update(extra or {})
    return JsonResponse(payload, status=status, json_dumps_params={'separators': (',', ':')})


def _serialized(project, segment):
    return serialize_company_segment(
        segment,
        state=segment_filter_state(project, segment),
        project_timezone=project.timezone,
    )


@login_required
@require_project_member
@require_GET
def project_company_segments(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return _segment_list_response(request, project)


@require_GET
def demo_company_segments(request):
    """The demo's seeded segments, listed for anonymous visitors.

    There is no demo counterpart to create, update, or delete: the demo project
    is read-only and its segments have no owner to save against.
    """

    project = get_demo_project()
    return _segment_list_response(
        request,
        project,
        segments=list_seeded_company_segments(project),
    )


@login_required
@require_project_member
@require_POST
def create_project_company_segment(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    try:
        payload = _json_payload(request)
        segment = create_company_segment(
            project,
            request.user,
            payload.get('name'),
            payload.get('definition'),
        )
    except CompanySegmentValidationError as exc:
        return _validation_response(exc)
    return _segment_list_response(
        request,
        project,
        status=201,
        extra={'segment': _serialized(project, segment)},
    )


@login_required
@require_project_member
@require_POST
def update_project_company_segment(request, project_id, segment_id):
    project = get_accessible_project_or_404(request.user, project_id)
    try:
        segment = get_company_segment(project, request.user, segment_id)
        payload = _json_payload(request)
        if 'definition' in payload:
            update_company_segment_definition(project, segment, payload.get('definition'))
        if 'name' in payload:
            rename_company_segment(project, request.user, segment, payload.get('name'))
    except CompanySegmentNotFound as exc:
        return _not_found_response(exc)
    except CompanySegmentValidationError as exc:
        return _validation_response(exc)
    return _segment_list_response(
        request,
        project,
        extra={'segment': _serialized(project, segment)},
    )


@login_required
@require_project_member
@require_POST
def delete_project_company_segment(request, project_id, segment_id):
    project = get_accessible_project_or_404(request.user, project_id)
    try:
        segment = get_company_segment(project, request.user, segment_id)
    except CompanySegmentNotFound as exc:
        return _not_found_response(exc)
    deleted = _serialized(project, segment)
    delete_company_segment(segment)
    return _segment_list_response(request, project, extra={'deletedSegment': deleted})
