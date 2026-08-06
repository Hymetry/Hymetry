import json
import math

from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_GET, require_POST

from apps.pages import services as pages_services
from apps.pages.models import PageCompanyDailyMetric

from .access import get_accessible_project_or_404, require_project_settings_editor
from .company_attributes import (
    CompanyAttributeValidationError,
    display_company_attribute_value,
    save_attribute_definitions,
    save_company_attribute_values,
    serialize_attributes,
    serialize_company_attribute_value,
    sort_company_attribute_value,
)
from .models import CompanyAttribute, CompanyAttributeValue
from .url_helpers import project_route


COMPANY_ATTRIBUTES_PAGE_SIZE = 10
COMPANY_ATTRIBUTES_MAX_REQUEST_BYTES = 1_000_000
COMPANY_ATTRIBUTES_DEFAULT_SORT = 'company'
COMPANY_ATTRIBUTES_SORT_DIRECTIONS = {'asc', 'desc'}


def _project_company_period(project):
    return pages_services.resolve_period(project.timezone, range_key='last_180_days')


def _all_visible_company_rows(project):
    start_date, end_date = _project_company_period(project)
    rows = (
        PageCompanyDailyMetric.objects
        .filter(project=project, date__gte=start_date, date__lte=end_date)
        .exclude(company_id='')
        .values('company_id')
        .annotate(company_name=Max('company_name_sample'), last_seen_date=Max('date'))
    )
    result = []
    for row in rows:
        company_id = str(row.get('company_id') or '').strip()
        if not company_id:
            continue
        company_name = str(row.get('company_name') or '').strip() or company_id
        result.append({
            'id': company_id,
            'name': company_name,
            'last_seen_date': row.get('last_seen_date'),
        })
    return result


def _normalize_table_request(request, attributes):
    query = str(request.GET.get('q') or '').strip()[:255]
    direction = str(request.GET.get('direction') or 'asc').lower()
    if direction not in COMPANY_ATTRIBUTES_SORT_DIRECTIONS:
        direction = 'asc'

    sort_key = str(request.GET.get('sort') or COMPANY_ATTRIBUTES_DEFAULT_SORT)
    sort_attribute = None
    if sort_key.startswith('attr:'):
        raw_attribute_id = sort_key.partition(':')[2]
        if raw_attribute_id.isdigit():
            sort_attribute = next(
                (attribute for attribute in attributes if attribute.id == int(raw_attribute_id)),
                None,
            )
        if sort_attribute is None:
            sort_key = COMPANY_ATTRIBUTES_DEFAULT_SORT
    elif sort_key != COMPANY_ATTRIBUTES_DEFAULT_SORT:
        sort_key = COMPANY_ATTRIBUTES_DEFAULT_SORT

    try:
        page_number = max(1, int(request.GET.get('page') or 1))
    except (TypeError, ValueError):
        page_number = 1

    return {
        'query': query,
        'direction': direction,
        'sort_key': sort_key,
        'sort_attribute': sort_attribute,
        'page': page_number,
    }


def _company_tie_key(row):
    return (row['name'].casefold(), row['id'].casefold())


def _sort_company_rows(rows, direction):
    return sorted(rows, key=_company_tie_key, reverse=direction == 'desc')


def _sort_attribute_rows(rows, attribute, direction):
    company_ids = [row['id'] for row in rows]
    values = {
        value.company_id: value
        for value in (
            CompanyAttributeValue.objects
            .filter(attribute=attribute, company_id__in=company_ids)
            .select_related('attribute', 'option')
        )
    }

    with_value = []
    without_value = []
    for row in rows:
        value = values.get(row['id'])
        sort_value = sort_company_attribute_value(value) if value is not None else None
        if sort_value is None:
            without_value.append(row)
        else:
            with_value.append((sort_value, row))

    # Stable two-step sorting keeps company name/id as an ascending tie-breaker
    # even when the primary value is descending. Missing values always remain last.
    with_value.sort(key=lambda item: _company_tie_key(item[1]))
    with_value.sort(key=lambda item: item[0], reverse=direction == 'desc')
    without_value.sort(key=_company_tie_key)
    return [row for _sort_value, row in with_value] + without_value


def _serialized_value(attribute, value):
    if value is None:
        return {
            'raw': None,
            'display': '-',
            'is_empty': True,
        }

    serialized = serialize_company_attribute_value(value)
    if not isinstance(serialized, dict):
        serialized = {'raw': serialized}
    serialized = dict(serialized)
    serialized.setdefault('display', display_company_attribute_value(attribute, value))
    serialized['is_empty'] = False
    return serialized


def _page_company_values(attributes, company_ids):
    attribute_by_id = {attribute.id: attribute for attribute in attributes}
    value_by_company_and_attribute = {
        (value.company_id, value.attribute_id): value
        for value in (
            CompanyAttributeValue.objects
            .filter(attribute__in=attributes, company_id__in=company_ids)
            .select_related('attribute', 'option')
        )
    }
    return {
        company_id: {
            str(attribute_id): _serialized_value(
                attribute,
                value_by_company_and_attribute.get((company_id, attribute_id)),
            )
            for attribute_id, attribute in attribute_by_id.items()
        }
        for company_id in company_ids
    }


def _build_company_attributes_table(project, request, *, attributes=None):
    attributes = list(
        attributes
        if attributes is not None
        else CompanyAttribute.objects.filter(project=project).prefetch_related('options').order_by('position', 'id')
    )
    request_state = _normalize_table_request(request, attributes)
    all_rows = _all_visible_company_rows(project)
    has_companies = bool(all_rows)

    query = request_state['query']
    if query:
        folded_query = query.casefold()
        rows = [row for row in all_rows if folded_query in row['name'].casefold()]
    else:
        rows = list(all_rows)

    if request_state['sort_attribute'] is not None:
        rows = _sort_attribute_rows(rows, request_state['sort_attribute'], request_state['direction'])
    else:
        rows = _sort_company_rows(rows, request_state['direction'])

    total = len(rows)
    total_pages = math.ceil(total / COMPANY_ATTRIBUTES_PAGE_SIZE) if total else 0
    page_number = request_state['page']
    if total_pages:
        page_number = min(page_number, total_pages)
    else:
        page_number = 1
    start = (page_number - 1) * COMPANY_ATTRIBUTES_PAGE_SIZE
    page_rows = rows[start:start + COMPANY_ATTRIBUTES_PAGE_SIZE]
    page_company_ids = [row['id'] for row in page_rows]
    values_by_company = _page_company_values(attributes, page_company_ids) if attributes else {
        company_id: {} for company_id in page_company_ids
    }

    companies = []
    for row in page_rows:
        companies.append({
            'id': row['id'],
            'name': row['name'],
            'detail_url': project_route(project, 'project_company_detail', company_id=row['id']),
            'values': values_by_company.get(row['id'], {}),
        })

    return {
        'has_companies': has_companies,
        'companies': companies,
        'pagination': {
            'page': page_number,
            'page_size': COMPANY_ATTRIBUTES_PAGE_SIZE,
            'total': total,
            'total_pages': total_pages,
            'has_previous': page_number > 1,
            'has_next': bool(total_pages and page_number < total_pages),
        },
        'sort': {
            'key': request_state['sort_key'],
            'direction': request_state['direction'],
        },
        'query': query,
    }


def _project_attributes(project):
    return list(
        CompanyAttribute.objects
        .filter(project=project)
        .prefetch_related('options')
        .order_by('position', 'id')
    )


def _initial_payload(project, request):
    attributes = _project_attributes(project)
    serialized_attributes = serialize_attributes(project)
    table = _build_company_attributes_table(project, request, attributes=attributes)
    return {
        'state': {
            'has_companies': table['has_companies'],
            'has_attributes': bool(attributes),
            'read_only': False,
        },
        'attributes': serialized_attributes,
        'table': {key: value for key, value in table.items() if key != 'has_companies'},
    }


def _json_request_payload(request):
    if len(request.body) > COMPANY_ATTRIBUTES_MAX_REQUEST_BYTES:
        raise CompanyAttributeValidationError({
            '_payload': {'payload': ['The request is too large.']},
        })
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompanyAttributeValidationError({
            '_payload': {'payload': ['Enter valid JSON.']},
        }) from exc
    if not isinstance(payload, dict):
        raise CompanyAttributeValidationError({
            '_payload': {'payload': ['The JSON payload must be an object.']},
        })
    return payload


def _validation_error_response(exc):
    return JsonResponse({'ok': False, 'errors': exc.errors}, status=400)


@login_required
@require_GET
@require_project_settings_editor
def project_company_attributes(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    payload = _initial_payload(project, request)
    values_url_template = project_route(
        project,
        'save_project_company_attribute_values',
        company_id='__company_id__',
    )
    context = {
        'project': project,
        'workspace': project.workspace,
        'company_attributes_payload_json': mark_safe(pages_services.to_json_script_text(payload)),
        'company_attributes_table_url': project_route(project, 'project_company_attributes_table_data'),
        'company_attributes_definitions_url': project_route(project, 'save_project_company_attributes'),
        'company_attribute_values_url_template': values_url_template,
        'company_detail_base_url': project_route(project, 'project_company_detail', company_id='__company_id__'),
    }
    return render(request, 'projects/company_attributes.html', context)


@login_required
@require_GET
@require_project_settings_editor
def project_company_attributes_table_data(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    table = _build_company_attributes_table(project, request)
    table.pop('has_companies', None)
    return JsonResponse({'ok': True, 'table': table})


@login_required
@require_POST
@require_project_settings_editor
def save_project_company_attributes(request, project_id):
    # Company attributes are the intentional Member+ exception to the demo project's general write block.
    project = get_accessible_project_or_404(request.user, project_id)
    try:
        payload = _json_request_payload(request)
        attributes = save_attribute_definitions(project, payload, actor=request.user)
    except CompanyAttributeValidationError as exc:
        return _validation_error_response(exc)
    return JsonResponse({'ok': True, 'attributes': attributes})


def _company_is_visible(project, company_id):
    start_date, end_date = _project_company_period(project)
    return (
        PageCompanyDailyMetric.objects
        .filter(
            project=project,
            company_id=company_id,
            date__gte=start_date,
            date__lte=end_date,
        )
        .exists()
    )


@login_required
@require_POST
@require_project_settings_editor
def save_project_company_attribute_values(request, project_id, company_id):
    # Keep value maintenance aligned with the definition permissions above.
    project = get_accessible_project_or_404(request.user, project_id)
    company_id = str(company_id or '').strip()
    if not company_id or not _company_is_visible(project, company_id):
        return JsonResponse({'ok': False, 'error': 'Company was not found.'}, status=404)
    try:
        payload = _json_request_payload(request)
        save_company_attribute_values(project, company_id, payload.get('values', payload))
    except CompanyAttributeValidationError as exc:
        return _validation_error_response(exc)

    attributes = _project_attributes(project)
    values = _page_company_values(attributes, [company_id]).get(company_id, {})
    return JsonResponse({'ok': True, 'company_id': company_id, 'values': values})
