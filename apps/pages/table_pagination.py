import math


DEFAULT_MAX_PAGE_SIZE = 100


def _to_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalized_sort_value(value):
    if value is None or value == '':
        return (0, '')
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, (int, float)):
        return (1, value)
    text = str(value).strip()
    if not text:
        return (0, '')
    try:
        return (1, float(text.replace(',', '').replace('%', '')))
    except (TypeError, ValueError):
        return (2, text.casefold())


def _sort_value(row, sort_key, sort_getters):
    getter = sort_getters.get(sort_key) or (lambda item: item.get(sort_key))
    return _normalized_sort_value(getter(row))


def paginate_cached_rows(
    rows,
    request,
    *,
    default_page_size,
    default_sort_key,
    default_sort_direction,
    sort_getters=None,
    fallback_getter=None,
    max_page_size=DEFAULT_MAX_PAGE_SIZE,
):
    rows = [row for row in (rows or []) if isinstance(row, dict)]
    sort_getters = sort_getters or {}
    fallback_getter = fallback_getter or (lambda row: row.get('name') or row.get('pageName') or row.get('page_name') or row.get('id') or '')
    sort_key = request.GET.get('sort') or default_sort_key
    if sort_getters and sort_key not in sort_getters:
        sort_key = default_sort_key
    sort_direction = str(request.GET.get('direction') or default_sort_direction).lower()
    if sort_direction not in {'asc', 'desc'}:
        sort_direction = default_sort_direction

    page_size = _to_int(request.GET.get('page_size') or request.GET.get('pageSize'), default_page_size)
    page_size = max(1, min(page_size, max_page_size))
    total_rows = len(rows)
    total_pages = max(1, math.ceil(total_rows / page_size))
    page = _to_int(request.GET.get('page'), 1)
    page = max(1, min(page, total_pages))

    sorted_rows = sorted(rows, key=lambda row: _normalized_sort_value(fallback_getter(row)))
    sorted_rows = sorted(
        sorted_rows,
        key=lambda row: _sort_value(row, sort_key, sort_getters),
        reverse=sort_direction == 'desc',
    )
    start = (page - 1) * page_size
    end = start + page_size

    return {
        'rows': sorted_rows[start:end],
        'pagination': {
            'page': page,
            'pageSize': page_size,
            'totalRows': total_rows,
            'totalPages': total_pages,
            'sortKey': sort_key,
            'sortDirection': sort_direction,
        },
    }
