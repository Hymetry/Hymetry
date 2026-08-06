from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.shortcuts import redirect
from django.utils.safestring import mark_safe

from apps.pages import services as pages_services

from .company_attribute_filters import (
    CompanyAttributeFilterState,
    apply_company_attribute_filters,
    canonicalize_company_attribute_query,
    serialize_company_attribute_filter_metadata,
)
from .company_segments import (
    SEGMENT_NAME_MAX_LENGTH,
    SEGMENT_QUERY_PARAMETER,
    CompanyScope,
)
from .url_helpers import project_route


def canonical_company_scope_redirect(request: Any, scope: CompanyScope):
    """
    Redirect when the URL does not already spell out the resolved scope.

    An active segment owns the ``ca.*`` pairs, so a stale or missing pair set —
    for example after the segment definition was edited in another tab —
    becomes a redirect rather than a URL that implies a cohort the server did
    not apply. A segment awaiting review owns them too, and owns them as empty:
    its id survives so the page can explain the refusal, while every pair the
    client sent with it is stripped.
    """

    submitted_segment = str(request.GET.get(SEGMENT_QUERY_PARAMETER) or "").strip()
    submitted_pairs = tuple(
        (str(key), str(value))
        for key in request.GET.keys()
        if str(key).startswith("ca.")
        for value in request.GET.getlist(key)
    )
    if (
        submitted_pairs == scope.state.canonical_pairs
        and submitted_segment == scope.url_segment_id
    ):
        return None

    query = canonicalize_company_attribute_query(request.GET, scope.state, reset_page=True)
    query.pop(SEGMENT_QUERY_PARAMETER, None)
    if scope.url_segment_id:
        query[SEGMENT_QUERY_PARAMETER] = scope.url_segment_id
    return _redirect_to_query(request, query)


def _redirect_to_query(request: Any, query: Any):
    encoded_query = query.urlencode()
    location = request.path
    if encoded_query:
        location = f"{location}?{encoded_query}"
    return redirect(location)


def company_identity_cohort_counts(
    queryset: QuerySet,
    state: CompanyAttributeFilterState,
    *,
    company_field: str = "company_id",
) -> dict[str, int]:
    """Count identified companies in a project/surface cohort."""

    known = (
        queryset
        .filter(**{f"{company_field}__isnull": False})
        .exclude(**{company_field: ""})
    )
    eligible_count = known.order_by().values(company_field).distinct().count()

    if state.active:
        matching_count = (
            apply_company_attribute_filters(
                known,
                state,
                company_field=company_field,
            )
            .order_by()
            .values(company_field)
            .distinct()
            .count()
        )
    else:
        matching_count = eligible_count

    return {
        "matching_count": matching_count,
        "eligible_count": eligible_count,
    }


def build_company_attribute_filter_context(
    project: Any,
    state: CompanyAttributeFilterState,
    *,
    surface: str,
    preview_url: str,
    preview: dict[str, int] | None = None,
    attributes: tuple[Any, ...] | list[Any] | None = None,
    scope: CompanyScope | None = None,
    segment_urls: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the one server/UI contract shared by all four overview pages."""

    metadata = serialize_company_attribute_filter_metadata(
        project,
        state,
        attributes=attributes,
    )
    scope_payload = (
        scope.to_payload()
        if scope is not None
        else {
            "type": "custom" if state.active else "all",
            "label": "Custom filter" if state.active else "All companies",
            "segmentId": "",
            "segmentName": "",
            "activeCount": state.active_count,
            "blockedSegmentId": "",
            "blockedSegmentName": "",
        }
    )
    segments_enabled = bool(scope is not None and scope.segments_enabled and segment_urls)
    # Listing and applying is one capability; creating, renaming, editing, and
    # deleting is another. The demo has the first without the second.
    segments_manageable = bool(
        segments_enabled
        and scope.segments_manageable
        and segment_urls.get("create")
    )
    review = (scope.review_notice if scope is not None else None) or {}
    payload = {
        "attributes": metadata["attributes"],
        "applied": state.applied,
        "canonicalPairs": [list(pair) for pair in state.canonical_pairs],
        "summaries": list(state.summaries),
        "activeCount": state.active_count,
        "preview": preview or {},
        "previewUrl": preview_url,
        "settingsUrl": project_route(project, "project_company_attributes"),
        "surface": surface,
        "scope": scope_payload,
        "segmentsEnabled": segments_enabled,
        "canManageSegments": segments_manageable,
        "segmentUrls": dict(segment_urls) if segments_enabled else {},
        "segmentNameMaxLength": SEGMENT_NAME_MAX_LENGTH,
        "segmentReview": {
            "active": bool(review.get("active")),
            "messages": list(review.get("messages") or []),
            "attributes": list(review.get("attributes") or []),
            "segmentCount": int(review.get("segmentCount") or 0),
        },
    }
    return {
        "company_attribute_filter": {
            "has_attributes": bool(payload["attributes"]),
            "active": state.active,
            "active_count": state.active_count,
            "summaries": list(state.summaries),
            "preview_url": preview_url,
            "settings_url": payload["settingsUrl"],
            "surface": surface,
            "scope_type": scope_payload["type"],
            "scope_label": scope_payload["label"],
            "segments_enabled": segments_enabled,
            "segments_manageable": segments_manageable,
            "blocked_segment_name": scope_payload["blockedSegmentName"],
        },
        # Rendered by the page rather than by script, so the warning survives a
        # failed or blocked script load exactly as the analytics numbers do.
        "company_segment_review": payload["segmentReview"],
        "company_attribute_filter_payload": payload,
        "company_attribute_filter_payload_json": mark_safe(
            pages_services.to_json_script_text(payload),
        ),
    }


__all__ = [
    "build_company_attribute_filter_context",
    "canonical_company_scope_redirect",
    "company_identity_cohort_counts",
]
