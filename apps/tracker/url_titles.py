from apps.projects.models import Project
from apps.tracker.models import AnalyticsEvent
from apps.tracker.page_naming import normalize_page_url_key


UNDEFINED_PAGE_NAME = 'Undefined'


def resolve_url_title(page_name, page_name_original, url):
    generated_title = (page_name or '').strip()
    original_title = (page_name_original or '').strip()
    fallback_url = (url or '').strip()

    if generated_title and generated_title != UNDEFINED_PAGE_NAME:
        return generated_title
    if original_title:
        return original_title
    return fallback_url


def get_latest_analytics_titles(project, urls, prefer_recording_titles=False):
    if isinstance(project, Project):
        project_id = project.id
    else:
        project_id = project

    distinct_urls = []
    normalized_by_url = {}
    for url in urls:
        if url is None:
            continue
        text = str(url).strip()
        if not text or text in normalized_by_url:
            continue
        distinct_urls.append(text)
        normalized_by_url[text] = normalize_page_url_key(text)
    if not distinct_urls:
        return {}

    distinct_normalized_urls = list(
        dict.fromkeys(
            normalized_url
            for normalized_url in normalized_by_url.values()
            if normalized_url
        )
    )
    if not distinct_normalized_urls:
        return {url: url for url in distinct_urls}

    analytics_lookup_urls = distinct_normalized_urls

    title_row_by_normalized_url = {}
    queryset = AnalyticsEvent.objects.none()
    if analytics_lookup_urls:
        queryset = (
            AnalyticsEvent.objects
            .filter(session__project_id=project_id, url_normalized__in=analytics_lookup_urls)
            .order_by('url_normalized', '-timestamp', '-id')
            .values('url_normalized', 'page_name', 'page_name_original')
        )

    for row in queryset.iterator(chunk_size=2000):
        normalized_url = (row.get('url_normalized') or '').strip()
        if not normalized_url or normalized_url in title_row_by_normalized_url:
            continue
        title_row_by_normalized_url[normalized_url] = {
            'page_name': row.get('page_name'),
            'page_name_original': row.get('page_name_original'),
        }
        if len(title_row_by_normalized_url) == len(analytics_lookup_urls):
            break

    title_map = {}
    for url in distinct_urls:
        normalized_url = normalized_by_url.get(url, '')
        title_row = title_row_by_normalized_url.get(normalized_url)
        if title_row is None:
            title_map[url] = url
            continue
        title_map[url] = resolve_url_title(
            title_row.get('page_name'),
            title_row.get('page_name_original'),
            url,
        )

    return title_map


def apply_titles_to_entries(
    project,
    entries,
    url_key='url',
    title_key='page_title',
    prefer_recording_titles=False,
):
    title_map = get_latest_analytics_titles(
        project,
        [entry.get(url_key, '') for entry in entries],
        prefer_recording_titles=prefer_recording_titles,
    )

    enriched_entries = []
    for entry in entries:
        url = entry.get(url_key, '')
        enriched_entry = dict(entry)
        enriched_entry[title_key] = title_map.get(url, url)
        enriched_entries.append(enriched_entry)

    return enriched_entries
