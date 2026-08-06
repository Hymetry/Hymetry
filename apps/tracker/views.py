import ipaddress
import logging
import re
import requests
import socket
import time
from urllib.parse import urlencode, urljoin, urlparse

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, RequestDataTooBig
from django.http import JsonResponse, Http404, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.projects import analytics_filter_state
from apps.projects.demo import DEMO_PROJECT_DISPLAY_NAME, get_demo_project
from apps.projects.access import get_accessible_project_or_404
from apps.projects.company_attribute_filter_support import (
    build_company_attribute_filter_context,
    canonical_company_scope_redirect,
)
from apps.projects.company_segments import (
    company_segment_urls,
    demo_company_segment_urls,
    resolve_company_scope,
)
from apps.projects.models import Project
from apps.projects.url_helpers import project_route
from apps.tracker.analytics_tracker import AnalyticsTracker
from apps.tracker.models import Session
from apps.tracker.replay_streaming import (
    ReplayStreamError,
    build_replay_stream_bootstrap,
    build_replay_stream_chunk,
    build_replay_stream_seek,
)
from apps.tracker.session_tracker import SessionTracker
from apps.tracker.session_resolver import SessionResolutionError
from apps.tracker.tools import get_consolidated_timeline_data
from apps.tracker.visits_filters import (
    normalize_entity_option_limit,
    resolve_visits_page_filter,
    search_visits_entities,
    selected_visits_entity_label,
    visits_page_filter_groups,
)
from apps.tracker.visits_table import build_visits_context

logger = logging.getLogger(__name__)

ASSET_PROXY_BLOCKED_HOSTS = {'localhost'}
ASSET_PROXY_CHUNK_SIZE = 64 * 1024
ASSET_PROXY_ALLOWED_CONTENT_TYPES = {
    'text/css',
    'image/avif',
    'image/bmp',
    'image/gif',
    'image/jpeg',
    'image/png',
    'image/webp',
    'image/x-icon',
    'image/vnd.microsoft.icon',
    'font/otf',
    'font/sfnt',
    'font/ttf',
    'font/woff',
    'font/woff2',
    'application/font-woff',
    'application/font-woff2',
    'application/vnd.ms-fontobject',
    'application/x-font-otf',
    'application/x-font-ttf',
    'application/x-font-woff',
    'application/x-font-woff2',
}
ASSET_PROXY_OCTET_STREAM_EXTENSIONS = {
    '.avif',
    '.bmp',
    '.eot',
    '.gif',
    '.ico',
    '.jpeg',
    '.jpg',
    '.otf',
    '.png',
    '.ttf',
    '.webp',
    '.woff',
    '.woff2',
}
ASSET_PROXY_REWRITABLE_CSS_URL_EXTENSIONS = ASSET_PROXY_OCTET_STREAM_EXTENSIONS | {
    '.css',
}


class AssetProxyError(ValueError):
    """Raised when an upstream asset URL is not safe to fetch."""


class AssetProxyTooLarge(AssetProxyError):
    """Raised when the upstream response exceeds the configured byte limit."""


class AssetProxyBlockedContentType(AssetProxyError):
    """Raised when the upstream content type is not safe to serve from this origin."""


def _get_current_rss_mb():
    """Return current process RSS in MB on Linux, or None when unavailable."""
    try:
        with open('/proc/self/status', encoding='utf-8') as status_file:
            for line in status_file:
                if line.startswith('VmRSS:'):
                    parts = line.split()
                    if len(parts) >= 2:
                        return round(int(parts[1]) / 1024, 2)
    except (OSError, ValueError):
        return None
    return None


def _is_proxyable_asset_url(url):
    if not url or not isinstance(url, str):
        return False

    candidate = url.strip()
    if not candidate:
        return False

    lower_candidate = candidate.lower()
    if (
        lower_candidate.startswith('data:')
        or lower_candidate.startswith('blob:')
        or lower_candidate.startswith('mailto:')
        or lower_candidate.startswith('tel:')
        or lower_candidate.startswith('javascript:')
        or candidate.startswith('#')
    ):
        return False

    parsed = urlparse(candidate)
    path = parsed.path.lower()
    return any(path.endswith(extension) for extension in ASSET_PROXY_REWRITABLE_CSS_URL_EXTENSIONS)


def _create_asset_proxy_url(request, target_url):
    return f"{request.build_absolute_uri('/asset-proxy')}?{urlencode({'url': target_url})}"


def _rewrite_css_asset_urls(css_text, base_url, request):
    def replace_css_url(match):
        quote = match.group(1) or ''
        raw_url = (match.group(2) or '').strip()
        if not _is_proxyable_asset_url(raw_url):
            return match.group(0)

        resolved_url = urljoin(base_url, raw_url)
        parsed = urlparse(resolved_url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            return match.group(0)

        proxied_url = _create_asset_proxy_url(request, resolved_url)
        return f'url({quote}{proxied_url}{quote})'

    return re.sub(
        r'url\(\s*([\'"]?)(?!data:|blob:)([^\'")]+)\1\s*\)',
        replace_css_url,
        css_text,
        flags=re.IGNORECASE,
    )


def _should_rewrite_css_response(target_url, content_type):
    content_type = (content_type or '').lower()
    path = urlparse(target_url).path.lower()
    return 'text/css' in content_type or path.endswith('.css')


def _is_blocked_asset_proxy_ip(address):
    ip = ipaddress.ip_address(address)
    return not ip.is_global or ip.is_multicast


def _get_asset_proxy_response_peer_ip(response):
    raw_response = getattr(response, 'raw', None)
    socket_candidates = [
        getattr(getattr(raw_response, '_connection', None), 'sock', None),
        getattr(
            getattr(getattr(getattr(raw_response, '_fp', None), 'fp', None), 'raw', None),
            '_sock',
            None,
        ),
    ]

    for sock in socket_candidates:
        getpeername = getattr(sock, 'getpeername', None)
        if not callable(getpeername):
            continue
        try:
            peer = getpeername()
        except OSError:
            continue
        if isinstance(peer, tuple) and peer and isinstance(peer[0], str):
            return peer[0]

    return None


def _validate_asset_proxy_response_peer(response):
    if getattr(settings, 'ASSET_PROXY_ALLOW_PRIVATE_HOSTS', False):
        return

    peer_ip = _get_asset_proxy_response_peer_ip(response)
    if not peer_ip:
        raise AssetProxyError('upstream peer could not be verified')
    if _is_blocked_asset_proxy_ip(peer_ip):
        raise AssetProxyError('blocked host')


def _asset_proxy_media_type(content_type):
    return (content_type or 'application/octet-stream').split(';', 1)[0].strip().lower()


def _asset_proxy_safe_content_type(content_type, media_type):
    sanitized = (content_type or media_type).splitlines()[0].strip()
    if sanitized.lower().startswith(media_type):
        return sanitized
    return media_type


def _validate_asset_proxy_content_type(target_url, content_type):
    media_type = _asset_proxy_media_type(content_type)
    path = urlparse(target_url).path.lower()

    if media_type in ASSET_PROXY_ALLOWED_CONTENT_TYPES:
        return _asset_proxy_safe_content_type(content_type, media_type)

    if media_type == 'application/octet-stream' and any(
        path.endswith(extension) for extension in ASSET_PROXY_OCTET_STREAM_EXTENSIONS
    ):
        return _asset_proxy_safe_content_type(content_type, media_type)

    raise AssetProxyBlockedContentType('blocked content type')


def _validate_asset_proxy_url(target_url):
    parsed = urlparse((target_url or '').strip())

    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise AssetProxyError('bad url')
    if parsed.username or parsed.password:
        raise AssetProxyError('bad url')

    if getattr(settings, 'ASSET_PROXY_ALLOW_PRIVATE_HOSTS', False):
        return parsed.geturl()

    hostname = parsed.hostname.lower()
    if hostname in ASSET_PROXY_BLOCKED_HOSTS or hostname.endswith('.localhost'):
        raise AssetProxyError('blocked host')

    try:
        addresses = [str(ipaddress.ip_address(hostname))]
    except ValueError:
        try:
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        except ValueError as exc:
            raise AssetProxyError('bad url') from exc
        try:
            address_info = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise AssetProxyError('host lookup failed') from exc
        addresses = sorted({info[4][0] for info in address_info})

    if not addresses or any(_is_blocked_asset_proxy_ip(address) for address in addresses):
        raise AssetProxyError('blocked host')

    return parsed.geturl()


def _fetch_asset_proxy_response(target_url, request):
    current_url = target_url
    max_redirects = int(getattr(settings, 'ASSET_PROXY_MAX_REDIRECTS', 3))
    timeout = float(getattr(settings, 'ASSET_PROXY_TIMEOUT_SECONDS', 10))

    for _ in range(max_redirects + 1):
        current_url = _validate_asset_proxy_url(current_url)
        response = requests.get(
            current_url,
            headers={'Origin': request.build_absolute_uri('/')},
            timeout=timeout,
            stream=True,
            allow_redirects=False,
        )
        try:
            _validate_asset_proxy_response_peer(response)
        except AssetProxyError:
            response.close()
            raise

        if response.is_redirect or response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get('Location')
            if not location:
                return current_url, response
            response.close()
            current_url = urljoin(current_url, location)
            continue

        return current_url, response

    raise AssetProxyError('too many redirects')


def _read_limited_asset_proxy_response(upstream_response):
    max_bytes = int(getattr(settings, 'ASSET_PROXY_MAX_BYTES', 5 * 1024 * 1024))
    content_length = upstream_response.headers.get('Content-Length')
    if content_length and content_length.isdigit() and int(content_length) > max_bytes:
        raise AssetProxyTooLarge('upstream response too large')

    chunks = []
    total_bytes = 0
    for chunk in upstream_response.iter_content(chunk_size=ASSET_PROXY_CHUNK_SIZE):
        if not chunk:
            continue
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise AssetProxyTooLarge('upstream response too large')
        chunks.append(chunk)

    return b''.join(chunks)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def record_event(request):
    """Record a single event or batch of events."""
    # Handle preflight request
    if request.method == "OPTIONS":
        response = JsonResponse({})
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    try:
        tracker = SessionTracker(request)
        if not tracker.parse_request():
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        if not tracker.project_uses_recording():
            response = JsonResponse({'status': 'ignored'})
            response["Access-Control-Allow-Origin"] = "*"
            return response

        # Find or create session
        tracker.find_session()

        # Process events
        tracker.process_events()

        # Update session activity after events are persisted
        tracker.update_session_activity()

        # Get response
        response = tracker.get_response()
        response["Access-Control-Allow-Origin"] = "*"
        return response

    except RequestDataTooBig:
        logger.warning(
            "Recording request body exceeded DATA_UPLOAD_MAX_MEMORY_SIZE",
            extra={'content_length': request.META.get('CONTENT_LENGTH')},
        )
        response = JsonResponse({'error': 'Payload too large.'}, status=413)
        response["Access-Control-Allow-Origin"] = "*"
        return response
    except PermissionDenied as e:
        response = JsonResponse({'error': str(e)}, status=403)
        response["Access-Control-Allow-Origin"] = "*"
        return response
    except SessionResolutionError:
        logger.warning("Recording request could not be assigned to one canonical session")
        response = JsonResponse({'error': 'Visit session could not be resolved.'}, status=409)
        response["Access-Control-Allow-Origin"] = "*"
        return response
    except Exception:
        logger.exception("Error processing recording request")
        response = JsonResponse({'error': 'Internal server error.'}, status=500)
        response["Access-Control-Allow-Origin"] = "*"
        return response


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def record_analytics(request):
    """Record analytics click events in batches."""
    if request.method == "OPTIONS":
        response = JsonResponse({})
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    tracker = AnalyticsTracker(request)

    try:
        if not tracker.parse_request():
            response = JsonResponse({'error': 'Invalid JSON'}, status=400)
            response["Access-Control-Allow-Origin"] = "*"
            return response

        tracker.process_events()
        response = tracker.get_response()
        response["Access-Control-Allow-Origin"] = "*"
        return response
    except PermissionDenied as e:
        response = JsonResponse({'error': str(e)}, status=403)
        response["Access-Control-Allow-Origin"] = "*"
        return response
    except Exception:
        logger.exception("Error processing analytics request")
        response = JsonResponse({'error': 'Internal server error.'}, status=500)
        response["Access-Control-Allow-Origin"] = "*"
        return response


@login_required
def recordings(request, project_id):
    """Render the recording-backed Visits table."""
    project = get_accessible_project_or_404(request.user, project_id)
    return _render_visits(request, project)


@login_required
@require_http_methods(["GET"])
def recording(request, project_id, session_id):
    """Display single rrweb player for a specific session with consolidated timeline."""
    project = get_accessible_project_or_404(request.user, project_id)
    session = _get_project_session_or_404(project.id, session_id)
    return _render_recording(request, project, session)


@login_required
@require_http_methods(["GET"])
def get_consolidated_data(request, project_id, session_id):
    """Ajax endpoint to get consolidated timeline data for a specific session."""
    started_at = time.perf_counter()
    memory_metrics = {
        'rss_before_mb': _get_current_rss_mb(),
    }

    def record_memory_checkpoint(stage, **details):
        rss_mb = _get_current_rss_mb()
        memory_metrics[f'rss_{stage}_mb'] = rss_mb
        memory_metrics.update({f'{stage}_{key}': value for key, value in details.items()})
        logger.info(
            "recording_data_memory_checkpoint session_id=%s project_id=%s stage=%s rss_mb=%s details=%s",
            session_id,
            project_id,
            stage,
            rss_mb,
            details,
        )

    logger.info(
        "recording_data_memory_checkpoint session_id=%s project_id=%s stage=before rss_mb=%s",
        session_id,
        project_id,
        memory_metrics['rss_before_mb'],
    )

    try:
        get_accessible_project_or_404(request.user, project_id)

        _get_project_session_or_404(project_id, session_id)
        consolidated_data = get_consolidated_timeline_data(
            request,
            session_id,
            allowed_project_ids=[project_id],
            memory_callback=record_memory_checkpoint,
        )

        record_memory_checkpoint(
            'before_json_dumps',
            event_count=len(consolidated_data.get('events', [])),
            tab_switch_count=len(consolidated_data.get('tab_switches', [])),
        )
        response = JsonResponse({
            'success': True,
            'data': consolidated_data
        })
        memory_metrics['rss_after_json_dumps_mb'] = _get_current_rss_mb()
        memory_metrics['response_bytes'] = len(response.content)
        memory_metrics['elapsed_ms'] = round((time.perf_counter() - started_at) * 1000)
        logger.info(
            "recording_data_memory_summary session_id=%s project_id=%s metrics=%s",
            session_id,
            project_id,
            memory_metrics,
        )
        return response
    except Session.DoesNotExist:
        return JsonResponse({'error': 'Session not found'}, status=404)
    except Exception as e:
        logger.exception("Error fetching consolidated recording data")
        return JsonResponse({'error': str(e)}, status=500)


def _replay_stream_response(*, project, session, cursor, seek_cursor, seek_ms):
    try:
        if seek_ms is not None:
            if cursor:
                raise ReplayStreamError(
                    "A replay request cannot combine chunk and seek cursors.",
                    code="invalid_seek_request",
                    status_code=400,
                )
            data = build_replay_stream_seek(
                project=project,
                session=session,
                seek_cursor=seek_cursor,
                target_ms=seek_ms,
            )
        elif cursor:
            data = build_replay_stream_chunk(
                project=project,
                session=session,
                cursor=cursor,
            )
        else:
            data = build_replay_stream_bootstrap(
                project=project,
                session=session,
            )
        response = JsonResponse(
            {'success': True, 'data': data},
            json_dumps_params={'separators': (',', ':')},
        )
        response['Cache-Control'] = 'private, no-store'
        logger.info(
            "recording_stream_chunk session_id=%s project_id=%s response_kind=%s "
            "event_count=%s event_bytes=%s payload_bytes=%s response_bytes=%s "
            "has_more=%s stop_reason=%s",
            session.session_id,
            project.id,
            data.get('response_kind', ''),
            data.get('chunk', {}).get('event_count', 0),
            data.get('chunk', {}).get('event_bytes', 0),
            data.get('chunk', {}).get('payload_bytes', 0),
            len(response.content),
            data.get('has_more', False),
            data.get('chunk', {}).get('stop_reason', ''),
        )
        return response
    except ReplayStreamError as exc:
        response = JsonResponse(
            {
                'success': False,
                'error': str(exc),
                'code': exc.code,
            },
            status=exc.status_code,
            json_dumps_params={'separators': (',', ':')},
        )
        response['Cache-Control'] = 'private, no-store'
        return response
    except Exception:
        logger.exception(
            "Unexpected replay stream failure session_id=%s project_id=%s",
            session.session_id,
            project.id,
        )
        response = JsonResponse(
            {
                'success': False,
                'error': 'Incremental replay is temporarily unavailable.',
                'code': 'streaming_unavailable',
            },
            status=500,
            json_dumps_params={'separators': (',', ':')},
        )
        response['Cache-Control'] = 'private, no-store'
        return response


@login_required
@require_http_methods(["GET"])
def replay_stream(request, project_id, session_id):
    """Return a bounded bootstrap, continuation chunk, or snapshot seek."""
    project = get_accessible_project_or_404(request.user, project_id)
    session = _get_project_session_or_404(project.id, session_id)
    return _replay_stream_response(
        project=project,
        session=session,
        cursor=request.GET.get('cursor'),
        seek_cursor=request.GET.get('seek_cursor'),
        seek_ms=request.GET.get('seek_ms') if 'seek_ms' in request.GET else None,
    )


def _get_project_session_or_404(project_id, session_id):
    try:
        return Session.objects.select_related('visitor__project').get(
            session_id=session_id,
            visitor__project_id=project_id,
        )
    except Session.DoesNotExist as exc:
        raise Http404('Session not found.') from exc


def _format_visits_duration(value):
    total_seconds = max(0, int(value or 0))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f'{hours}h')
    if minutes:
        parts.append(f'{minutes}m')
    if seconds or not parts:
        parts.append(f'{seconds}s')
    return ' '.join(parts)


def _visits_query_url(*, range_key, sort_key, sort_direction, page=None, filters=None):
    query = [
        ('range', range_key),
        ('sort', sort_key),
        ('direction', sort_direction),
    ]
    if filters:
        if hasattr(filters, 'lists'):
            for key, values in filters.lists():
                query.extend((key, value) for value in values)
        elif hasattr(filters, 'items'):
            query.extend(filters.items())
        else:
            query.extend(filters)
    if page is not None:
        query.append(('page', page))
    return f'?{urlencode(query, doseq=True)}'


def _render_visits(request, project, *, is_demo_view=False):
    company_scope = resolve_company_scope(request, project, is_demo_view=is_demo_view)
    company_attribute_state = company_scope.state
    canonical_redirect = canonical_company_scope_redirect(request, company_scope)
    if canonical_redirect is not None:
        return canonical_redirect
    restored = analytics_filter_state.restore_redirect(
        request,
        project,
        analytics_filter_state.VISITS,
        is_demo_view=is_demo_view,
    )
    if restored is not None:
        return restored
    entity_type = request.GET.get('entity_type')
    entity_id = str(request.GET.get('entity_id') or '').strip()
    if entity_type not in {'company', 'user'} or not entity_id:
        entity_type = ''
        entity_id = ''

    page_filter_groups = visits_page_filter_groups(project)
    page_selection = resolve_visits_page_filter(
        page_filter_groups,
        request.GET.get('page_filter_type'),
        request.GET.get('page_filter_id'),
    )
    context = build_visits_context(
        project,
        range_key=request.GET.get('range'),
        sort_key=request.GET.get('sort'),
        sort_direction=request.GET.get('direction'),
        entity_type=entity_type,
        entity_id=entity_id,
        page_filter_type=page_selection['type'],
        page_filter_id=page_selection['id'],
        page_number=request.GET.get('page', 1),
        company_attribute_state=company_attribute_state,
    )
    range_key = context['visits_range_key']
    sort_key = context['visits_sort_key']
    sort_direction = context['visits_sort_direction']
    filter_params = []
    if entity_type and entity_id:
        filter_params.extend((
            ('entity_type', entity_type),
            ('entity_id', entity_id),
        ))
    if page_selection['type'] and page_selection['id']:
        filter_params.extend((
            ('page_filter_type', page_selection['type']),
            ('page_filter_id', page_selection['id']),
        ))
    filter_params.extend(company_scope.canonical_pairs)

    for row in context['visit_rows']:
        session_id = row['recording_session_id']
        if is_demo_view:
            replay_url = reverse('demo_recording', kwargs={'session_id': session_id})
            user_url = (
                reverse('demo_user_detail', kwargs={'user_id': row['user_id']})
                if row['user_id']
                else ''
            )
            company_url = (
                reverse('demo_company_detail', kwargs={'company_id': row['company_id']})
                if row['company_id']
                else ''
            )
        else:
            replay_url = project_route(
                project,
                'recording',
                session_id=session_id,
            )
            user_url = (
                project_route(project, 'project_user_detail', user_id=row['user_id'])
                if row['user_id']
                else ''
            )
            company_url = (
                project_route(project, 'project_company_detail', company_id=row['company_id'])
                if row['company_id']
                else ''
            )

        entity_query = urlencode({'range': range_key})
        row.update({
            # Replay always routes with the recording Session UUID. Linked
            # AnalyticsSession/AnalyticsEvent identifiers are attribution only.
            'replay_url': replay_url,
            'user_url': f'{user_url}?{entity_query}' if user_url else '',
            'company_url': f'{company_url}?{entity_query}' if company_url else '',
            'user_label': row['user_name'],
            'company_label': row['company_name'],
            'duration_label': _format_visits_duration(row['duration_seconds']),
            'unique_pages_label': (
                f"{row['unique_pages']} page"
                f"{'s' if row['unique_pages'] != 1 else ''}"
            ),
            'chart_data': row['segments'],
        })

    sort_urls = {}
    for key in ('user', 'company', 'date_time', 'duration', 'unique_pages'):
        if key == sort_key:
            direction = 'desc' if sort_direction == 'asc' else 'asc'
        else:
            direction = 'asc' if key in {'user', 'company'} else 'desc'
        sort_urls[key] = _visits_query_url(
            range_key=range_key,
            sort_key=key,
            sort_direction=direction,
            filters=filter_params,
        )

    page_obj = context['page_obj']
    preview_url = (
        reverse('demo_company_attribute_filter_preview')
        if is_demo_view
        else project_route(project, 'project_company_attribute_filter_preview')
    )
    context.update({
        'project': project,
        'selected_project': project,
        'project_id': project.id,
        'is_demo_view': is_demo_view,
        'demo_project_id': project.id if is_demo_view else None,
        'demo_project_display_name': DEMO_PROJECT_DISPLAY_NAME,
        'sort_urls': sort_urls,
        'visits_range_urls': {
            range_option: _visits_query_url(
                range_key=range_option,
                sort_key=sort_key,
                sort_direction=sort_direction,
                filters=filter_params,
            )
            for range_option in ('last_7_days', 'last_30_days')
        },
        'visits_entity_label': selected_visits_entity_label(
            project,
            entity_type,
            entity_id,
            range_key=range_key,
        ),
        'visits_entity_options_url': (
            reverse('demo_visits_filter_options')
            if is_demo_view
            else project_route(project, 'visits_filter_options')
        ),
        'visits_page_filter_groups': page_filter_groups,
        'visits_page_filter_label': page_selection['label'],
        'previous_url': (
            _visits_query_url(
                range_key=range_key,
                sort_key=sort_key,
                sort_direction=sort_direction,
                page=page_obj.previous_page_number(),
                filters=filter_params,
            )
            if page_obj.has_previous()
            else ''
        ),
        'next_url': (
            _visits_query_url(
                range_key=range_key,
                sort_key=sort_key,
                sort_direction=sort_direction,
                page=page_obj.next_page_number(),
                filters=filter_params,
            )
            if page_obj.has_next()
            else ''
        ),
        **build_company_attribute_filter_context(
            project,
            company_attribute_state,
            surface='visits',
            preview_url=preview_url,
            scope=company_scope,
            segment_urls=(
                demo_company_segment_urls()
                if is_demo_view
                else company_segment_urls(project)
            ),
        ),
    })
    analytics_filter_state.remember(
        request,
        project,
        analytics_filter_state.VISITS,
        scope=company_scope,
        page_values={
            'range': range_key,
            'entity_type': entity_type,
            'entity_id': entity_id,
            'page_filter_type': page_selection['type'],
            'page_filter_id': page_selection['id'],
        },
        is_demo_view=is_demo_view,
    )
    return render(request, 'tracker/visits.html', context)


def _visits_filter_options_response(request, project):
    payload = search_visits_entities(
        project,
        query=request.GET.get('q') or request.GET.get('query'),
        limit=normalize_entity_option_limit(request.GET.get('limit')),
        range_key=request.GET.get('range'),
    )
    return JsonResponse(
        payload,
        status=202 if payload['pending'] else 200,
        json_dumps_params={'separators': (',', ':')},
    )


@login_required
@require_http_methods(["GET"])
def visits_filter_options(request, project_id):
    project = get_accessible_project_or_404(request.user, project_id)
    return _visits_filter_options_response(request, project)


def _render_recording(request, project, session, *, is_demo_view=False):
    return render(
        request,
        'tracker/recording.html',
        {
            'session': session,
            'project': project,
            'project_id': project.id,
            'session_id': session.session_id,
            'is_demo_view': is_demo_view,
            'demo_project_id': project.id if is_demo_view else None,
            'demo_project_display_name': DEMO_PROJECT_DISPLAY_NAME,
        },
    )


@require_http_methods(["GET"])
def demo_recordings(request):
    return _render_visits(request, get_demo_project(), is_demo_view=True)


@require_http_methods(["GET"])
def demo_visits_filter_options(request):
    return _visits_filter_options_response(request, get_demo_project())


@require_http_methods(["GET"])
def demo_recording(request, session_id):
    project = get_demo_project()
    session = _get_project_session_or_404(project.id, session_id)
    return _render_recording(request, project, session, is_demo_view=True)


@require_http_methods(["GET"])
def demo_get_consolidated_data(request, session_id):
    try:
        project = get_demo_project()
        _get_project_session_or_404(project.id, session_id)
        consolidated_data = get_consolidated_timeline_data(
            request,
            session_id,
            allowed_project_ids=[project.id],
        )

        return JsonResponse({
            'success': True,
            'data': consolidated_data,
        })
    except Http404:
        return JsonResponse({'error': 'Session not found'}, status=404)
    except Exception as e:
        logger.exception("Error fetching demo consolidated recording data")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def demo_replay_stream(request, session_id):
    """Public bounded replay stream scoped to the fixed synthetic project."""
    project = get_demo_project()
    session = _get_project_session_or_404(project.id, session_id)
    return _replay_stream_response(
        project=project,
        session=session,
        cursor=request.GET.get('cursor'),
        seek_cursor=request.GET.get('seek_cursor'),
        seek_ms=request.GET.get('seek_ms') if 'seek_ms' in request.GET else None,
    )


@csrf_exempt
@require_http_methods(["GET", "HEAD", "OPTIONS"])
def asset_proxy(request):
    """
    Proxy external assets to solve CORS issues.
    Replaces the Cloudflare worker for self-hosted deployments.
    """
    # Handle CORS preflight
    if request.method == "OPTIONS":
        response = HttpResponse()
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type"
        response["Access-Control-Max-Age"] = "86400"
        return response

    target_url = request.GET.get('url')
    if not target_url:
        return HttpResponse("missing ?url=", status=400)

    try:
        final_url, upstream_response = _fetch_asset_proxy_response(target_url, request)
        try:
            content_type = upstream_response.headers.get('Content-Type', 'application/octet-stream')
            content_type = _validate_asset_proxy_content_type(final_url, content_type)
            response_content = _read_limited_asset_proxy_response(upstream_response)
        finally:
            upstream_response.close()

        if _should_rewrite_css_response(final_url, content_type):
            encoding = upstream_response.encoding or 'utf-8'
            css_text = response_content.decode(encoding, errors='replace')
            response_content = _rewrite_css_asset_urls(css_text, final_url, request).encode(encoding)

        # Create response with the upstream content
        response = HttpResponse(
            response_content,
            status=upstream_response.status_code,
            content_type=content_type,
        )

        # Add CORS headers
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
        response["Vary"] = "Origin"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"

        # Set cache headers if not present
        if 'Cache-Control' not in upstream_response.headers:
            response["Cache-Control"] = "public, max-age=2592000"
        else:
            response["Cache-Control"] = upstream_response.headers['Cache-Control']

        return response

    except AssetProxyTooLarge:
        return HttpResponse("upstream response too large", status=502)
    except AssetProxyBlockedContentType as e:
        return HttpResponse(str(e), status=415)
    except AssetProxyError as e:
        return HttpResponse(str(e), status=403 if 'blocked' in str(e) else 400)
    except requests.Timeout:
        return HttpResponse("upstream timeout", status=504)
    except requests.RequestException:
        return HttpResponse("upstream error", status=502)
