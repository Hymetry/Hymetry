from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.pages import services as pages_services
from apps.pages.models import PageVisit

from .access import get_accessible_project_or_404
from .company_attribute_filter_support import company_identity_cohort_counts
from .company_attribute_filters import (
    CompanyAttributeFilterValidationError,
    parse_company_attribute_filters,
)
from .decorators import require_project_member
from .demo import get_demo_project


SUPPORTED_SURFACES = {"companies", "users", "pages", "visits"}
SUPPORTED_RANGES = {
    "last_7_days",
    "last_30_days",
    "last_90_days",
    "last_180_days",
}
PERIOD_RANGE_KEYS = {
    7: "last_7_days",
    30: "last_30_days",
    90: "last_90_days",
    180: "last_180_days",
}


def _range_key(request):
    period = request.GET.get("period")
    try:
        period_days = int(str(period or "").rstrip("d")) if period is not None else None
    except (TypeError, ValueError):
        period_days = None
    if period_days in PERIOD_RANGE_KEYS:
        return PERIOD_RANGE_KEYS[period_days]
    value = request.GET.get("range") or "last_30_days"
    return value if value in SUPPORTED_RANGES else "last_30_days"


def overview_visit_queryset(request, project, surface):
    start_date, end_date = pages_services.resolve_period(
        project.timezone,
        range_key=_range_key(request),
    )
    start_ts, end_ts = pages_services._utc_bounds_for_local_dates(
        start_date,
        end_date,
        project.timezone,
    )
    queryset = PageVisit.objects.filter(
        project=project,
        visit_start_ts__gte=start_ts,
        visit_start_ts__lt=end_ts,
    )

    if surface == "pages":
        product_areas = [
            str(value).strip()
            for value in request.GET.getlist("product_area")
            if str(value).strip()
        ]
        if product_areas:
            queryset = queryset.filter(product_area_key__in=product_areas)
    elif surface == "companies":
        query = str(request.GET.get("q") or "").strip()
        if query:
            queryset = queryset.filter(
                Q(company_id__icontains=query)
                | Q(company_name_sample__icontains=query),
            )
    elif surface == "users":
        company = str(request.GET.get("company") or "").strip()
        if company:
            queryset = queryset.filter(
                Q(company_id=company) | Q(company_name_sample=company),
            )
        query = str(request.GET.get("q") or "").strip()
        if query:
            queryset = queryset.filter(
                Q(user_id__icontains=query)
                | Q(user_name_sample__icontains=query)
                | Q(company_name_sample__icontains=query),
            )
    return queryset


def _preview_response(request, project):
    surface = str(request.GET.get("surface") or "").strip().lower()
    if surface not in SUPPORTED_SURFACES:
        return JsonResponse(
            {"error": "Select a supported analytics surface."},
            status=400,
        )

    try:
        state = parse_company_attribute_filters(project, request.GET, strict=True)
    except CompanyAttributeFilterValidationError as exc:
        return JsonResponse(
            {"error": "Invalid company attribute filters.", "issues": exc.errors},
            status=400,
        )

    if surface == "visits":
        from apps.tracker.visits_table import company_attribute_preview_counts

        counts = company_attribute_preview_counts(project, request, state)
    else:
        counts = company_identity_cohort_counts(
            overview_visit_queryset(request, project, surface),
            state,
            company_field="company_id",
        )

    eligible_count = counts["eligible_count"]
    matching_count = counts["matching_count"]
    percentage = round(matching_count / eligible_count * 100, 1) if eligible_count else 0
    return JsonResponse(
        {
            "surface": surface,
            "matching_count": matching_count,
            "eligible_count": eligible_count,
            "percentage": percentage,
            "canonicalPairs": [list(pair) for pair in state.canonical_pairs],
        },
        json_dumps_params={"separators": (",", ":")},
    )


@login_required
@require_project_member
@require_GET
def project_company_attribute_filter_preview(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return _preview_response(request, project)


@require_GET
def demo_company_attribute_filter_preview(request):
    return _preview_response(request, get_demo_project())
