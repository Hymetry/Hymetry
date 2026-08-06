import json
import re
from collections import defaultdict
from django.utils import timezone
from urllib.parse import urlencode, urljoin, urlparse

from apps.tracker.analytics_replay_timeline import build_analytics_replay_timeline
from apps.tracker.models import Session
from apps.tracker.replayability import is_replayable_full_snapshot
from config.runtime_url_values import runtime_urls


def _resolve_allowed_project_ids(request, allowed_project_ids=None):
    if allowed_project_ids is not None:
        return list(allowed_project_ids)

    if not getattr(request.user, 'is_authenticated', False):
        return []

    from apps.projects.access import active_workspace_memberships
    from apps.projects.models import Project

    workspace_ids = active_workspace_memberships().filter(user=request.user).values_list('workspace_id', flat=True)
    return list(
        Project.active.filter(workspace_id__in=workspace_ids).values_list('id', flat=True)
    )


def get_session_only(request, session_id, allowed_project_ids=None):
    """Get authorized session without querying events."""
    user_projects = _resolve_allowed_project_ids(request, allowed_project_ids=allowed_project_ids)
    session = Session.objects.select_related('visitor__project').get(
        session_id=session_id,
        visitor__project__in=user_projects
    )
    return session

def replace_urls_with_proxy(events_data, base_url=None):
    """
    Replace external resource URLs in events data with CloudFlare proxy URLs.
    This function processes the events data and replaces external resource URLs
    (CSS, JS, images, fonts, etc.) with CloudFlare proxy URLs to solve CORS issues.
    """
    if isinstance(events_data, str):
        events_data = json.loads(events_data)
    domain_url = runtime_urls.get_hymetry_domain().rstrip('/')

    def get_event_base_url(obj):
        """Return the recorded page URL from an rrweb Meta event, when available."""
        if not isinstance(obj, dict) or obj.get('type') != 4:
            return None
        data = obj.get('data')
        if not isinstance(data, dict):
            return None
        href = data.get('href')
        if is_http_url(href):
            return href
        return None

    def find_recording_base_url(obj):
        """Find a recorded page URL so relative asset URLs can be replayed correctly."""
        if isinstance(obj, dict):
            event_base_url = get_event_base_url(obj)
            if event_base_url:
                return event_base_url
            for value in obj.values():
                found = find_recording_base_url(value)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = find_recording_base_url(item)
                if found:
                    return found
        return None
    
    def replace_urls_in_object(obj, current_base_url=None):
        """Recursively replace URLs in an object."""
        if isinstance(obj, dict):
            current_base_url = get_event_base_url(obj) or current_base_url
            normalize_replay_resource_attributes(obj, current_base_url)
            for key, value in obj.items():
                if isinstance(value, str):
                    resource_url = get_proxyable_resource_url(value, current_base_url)
                    if resource_url:
                        obj[key] = create_proxy_url(resource_url)
                    else:
                        obj[key] = replace_urls_in_text(value, current_base_url)
                elif isinstance(value, (dict, list)):
                    replace_urls_in_object(value, current_base_url)
        elif isinstance(obj, list):
            active_base_url = current_base_url
            for item in obj:
                item_base_url = get_event_base_url(item) or active_base_url
                replace_urls_in_object(item, item_base_url)
                active_base_url = get_event_base_url(item) or active_base_url
    
    def is_http_url(url):
        if not url or not isinstance(url, str):
            return False
        try:
            parsed = urlparse(url)
            return parsed.scheme in ['http', 'https'] and bool(parsed.netloc)
        except Exception:
            return False

    def is_relative_url_candidate(candidate):
        if any(ch.isspace() for ch in candidate):
            return False
        if any(ch in candidate for ch in ['<', '>', '"', "'", '{', '}', '(', ')']):
            return False
        return (
            candidate.startswith('/')
            or candidate.startswith('./')
            or candidate.startswith('../')
            or is_resource_url(candidate)
        )

    def resolve_url(url, current_base_url=None):
        """Resolve absolute and recorded-page-relative resource URLs."""
        if not url or not isinstance(url, str):
            return None

        candidate = url.strip()
        if not candidate:
            return None

        lower_candidate = candidate.lower()
        if (
            lower_candidate.startswith('data:')
            or lower_candidate.startswith('blob:')
            or lower_candidate.startswith('mailto:')
            or lower_candidate.startswith('tel:')
            or lower_candidate.startswith('javascript:')
            or candidate.startswith('#')
        ):
            return None

        try:
            parsed = urlparse(candidate)
            if parsed.scheme in ['http', 'https'] and parsed.netloc:
                return candidate
            if parsed.scheme:
                return None
            if current_base_url and is_relative_url_candidate(candidate):
                return urljoin(current_base_url, candidate)
        except Exception:
            return None

        return None

    def get_proxyable_resource_url(url, current_base_url=None):
        """Return the absolute resource URL that should be proxied, if any."""
        resolved_url = resolve_url(url, current_base_url)
        if not resolved_url:
            return None

        parsed = urlparse(resolved_url)
        app_domain = urlparse(domain_url).netloc
        app_host = urlparse(domain_url).hostname
        own_domains = {app_domain, app_host, 'localhost', '127.0.0.1'}
        if parsed.netloc in own_domains or parsed.hostname in own_domains:
            return None

        if is_resource_url(resolved_url):
            return resolved_url

        return None

    def normalize_replay_resource_attributes(obj, current_base_url=None):
        """Make captured resource hints act like applied styles during replay."""
        if not isinstance(obj, dict):
            return

        tag_name = str(obj.get('tagName') or '').lower()
        attributes = obj.get('attributes')
        if tag_name != 'link' or not isinstance(attributes, dict):
            return

        rel = str(attributes.get('rel') or '').lower()
        rel_tokens = set(rel.split())
        as_attr = str(attributes.get('as') or '').lower()
        href = attributes.get('href')

        if 'preload' in rel_tokens and 'stylesheet' not in rel_tokens and as_attr == 'style' and href:
            attributes['rel'] = 'stylesheet'
            attributes.pop('as', None)
            attributes.pop('onload', None)
    
    def is_resource_url(url):
        """Check if URL is a web resource that should be proxied."""
        if not url:
            return False
        
        # Keep this list aligned with the asset proxy's passive safe content types.
        resource_extensions = {
            # Stylesheets
            '.css',
            # Images that cannot execute script when served from our origin
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.avif', '.ico',
            # Fonts
            '.woff', '.woff2', '.ttf', '.otf', '.eot',
        }
        
        # Check file extension
        url_lower = url.lower()
        for ext in resource_extensions:
            if url_lower.endswith(ext):
                return True
        
        # Check for common resource patterns in URLs
        resource_patterns = [
            r'\.(css|png|jpg|jpeg|gif|bmp|webp|avif|ico|woff|woff2|ttf|otf|eot)(?:$|[?#])',
            r'\.(min|bundle|vendor)\.css(?:$|[?#])',
        ]
        
        import re
        for pattern in resource_patterns:
            if re.search(pattern, url_lower, re.IGNORECASE):
                return True
        
        return False
    
    def create_proxy_url(original_url):
        """Create an asset proxy URL."""
        return f"{domain_url}/asset-proxy?{urlencode({'url': original_url})}"
    
    def replace_urls_in_text(text, current_base_url=None):
        """Replace resource URLs in any text content with proxy URLs."""
        if not isinstance(text, str):
            return text
        
        import re
        
        # Replace URLs in CSS url() declarations
        def replace_css_url(match):
            url_content = match.group(1)
            url_content = url_content.strip('"\'')
            resource_url = get_proxyable_resource_url(url_content, current_base_url)
            if resource_url:
                return f'url("{create_proxy_url(resource_url)}")'
            return match.group(0)
        
        # Replace URLs in CSS @import statements
        def replace_css_import(match):
            import_url = match.group(1)
            resource_url = get_proxyable_resource_url(import_url, current_base_url)
            if resource_url:
                return f'@import "{create_proxy_url(resource_url)}"'
            return match.group(0)

        def replace_css_import_url(match):
            import_url = match.group(1).strip('"\'')
            resource_url = get_proxyable_resource_url(import_url, current_base_url)
            if resource_url:
                return f'@import url("{create_proxy_url(resource_url)}")'
            return match.group(0)
        
        # Replace URLs in HTML attributes
        def replace_html_url(match):
            attr_name = match.group(1)
            url_content = match.group(2)
            resource_url = get_proxyable_resource_url(url_content, current_base_url)
            if resource_url:
                return f'{attr_name}="{create_proxy_url(resource_url)}"'
            return match.group(0)
        
        # Apply all replacements
        text = re.sub(r'url\(["\']?([^"\')\s]+)["\']?\)', replace_css_url, text)
        text = re.sub(r'@import\s+["\']([^"\']+)["\']', replace_css_import, text)
        text = re.sub(r'@import\s+url\(["\']?([^"\')\s]+)["\']?\)', replace_css_import_url, text)
        text = re.sub(r'(src|href|data-src)=["\']([^"\']+)["\']', replace_html_url, text)
        
        return text
    
    # Process the events data
    resolved_base_url = base_url or find_recording_base_url(events_data)
    replace_urls_in_object(events_data, resolved_base_url)
    
    return events_data


def get_session_and_events(request, session_id, allowed_project_ids=None):
    """Get session and events data with optimized queries."""
    user_projects = _resolve_allowed_project_ids(request, allowed_project_ids=allowed_project_ids)
    session = Session.objects.select_related('visitor__project').get(
        session_id=session_id, 
        visitor__project__in=user_projects
    )
    events = session.events.order_by('timestamp')
    return session, events


def is_valid_rrweb_event(event_data, valid_types=None):
    """Check if event is a valid rrweb event."""
    if valid_types is None:
        # Default valid rrweb event types: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14
        valid_types = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14}
    
    if not isinstance(event_data, dict):
        return False

    event_type = event_data.get('type')
    # Skip custom events like 'session_start'
    if isinstance(event_type, str):
        return False
    # Only include numeric event types that are valid rrweb types
    return isinstance(event_type, (int, float)) and event_type in valid_types


def get_timestamp_for_sorting(event_data):
    """Extract timestamp from event data and convert to comparable format."""
    timestamp = event_data.get('timestamp', 0)
    
    # Handle different timestamp formats
    if isinstance(timestamp, str):
        try:
            # Try to convert string timestamp to float/int
            return float(timestamp)
        except (ValueError, TypeError):
            # If conversion fails, use 0 as fallback
            return 0
    elif isinstance(timestamp, (int, float)):
        return timestamp
    else:
        return 0


def get_pages_data(request, session_id, allowed_project_ids=None):
    session, events = get_session_and_events(
        request,
        session_id,
        allowed_project_ids=allowed_project_ids,
    )
    event_records = list(events)
    events_data = [event.data for event in event_records]

    # Filter out non-rrweb events and sort by timestamp
    if events_data:
        # Filter events to only include valid rrweb events
        events_data = [event for event in events_data if is_valid_rrweb_event(event)]
        
        # Sort events by timestamp
        events_data.sort(key=get_timestamp_for_sorting)
        
        # Replace external URLs with proxy URLs
        base_url = next((event.url for event in event_records if event.url), None)
        events_data = replace_urls_with_proxy(events_data, base_url=base_url)

    return json.dumps(events_data, indent=2).replace('</', '<\\/')


def get_tab_timeline_data(request, session_id, allowed_project_ids=None):
    """Get timeline data for multi-tab recording playback."""
    session, events = get_session_and_events(
        request,
        session_id,
        allowed_project_ids=allowed_project_ids,
    )
    
    # Group events by tab_id
    tab_events = defaultdict(list)
    tab_timeline = []
    
    # Valid rrweb event types for timeline (subset of all valid types)
    valid_rrweb_types = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14}
    
    # Process events and build timeline
    session_start_time = None
    
    for event in events:
        event_data = event.data
        
        # Skip invalid rrweb events
        if not is_valid_rrweb_event(event_data, valid_rrweb_types):
            continue
            
        tab_id = event.tab_id or 'unknown'
        timestamp = get_timestamp_for_sorting(event_data)
        
        # Use the first event timestamp as session start time
        if session_start_time is None:
            session_start_time = timestamp
        
        # Keep absolute timestamps for events, but calculate relative for timeline
        relative_timestamp = timestamp - session_start_time if session_start_time else 0
        
        # Add event to tab's event list (keep original timestamp)
        tab_events[tab_id].append({
            'data': event_data,
            'timestamp': timestamp,  # Keep absolute timestamp
            'relative_timestamp': relative_timestamp,
            'db_timestamp': event.timestamp.isoformat(),
            'page_url': event.url,
        })
        
        # Add timeline entry for this tab at this timestamp
        tab_timeline.append({
            'tab_id': tab_id,
            'timestamp': relative_timestamp,  # Use relative for timeline
            'absolute_timestamp': timestamp,
            'db_timestamp': event.timestamp.isoformat()
        })
    
    # Sort timeline by timestamp
    tab_timeline.sort(key=lambda x: x['timestamp'])
    
    # Prepare final data structure
    result = {
        'timeline': tab_timeline,
        'tabs': {}
    }
    
    # Process each tab's events
    for tab_id, events_list in tab_events.items():
        # Sort events by timestamp
        events_list.sort(key=lambda x: x['timestamp'])
        
        # Extract just the event data for rrweb player and ensure proper format
        events_data = []
        has_dom_snapshot = False
        dom_snapshot_event = None
        
        for event in events_list:
            event_data = event['data'].copy()  # Make a copy to avoid modifying original
            
            # Ensure event has a timestamp
            if 'timestamp' not in event_data:
                event_data['timestamp'] = event['timestamp']
            
            # Ensure event has a type
            if 'type' not in event_data:
                event_data['type'] = 0  # Default to full snapshot
            
            # Track if we have a DOM snapshot and preserve it
            if event_data.get('type') == 2:
                has_dom_snapshot = True
                dom_snapshot_event = event_data  # Preserve the original DOM snapshot
            
            # Normalize the event structure for rrweb player
            # rrweb expects events in the format: {type: number, data: object, timestamp: number}
            # For type 3 events (input), the data should be the actual input data, not nested
            event_type = event_data.get('type', 0)
            
            if event_type == 3:  # Input events
                # For input events, use the data directly without nesting
                normalized_event = {
                    'type': event_type,
                    'data': event_data.get('data', {}),  # Use the actual input data
                    'timestamp': event_data.get('timestamp', event['timestamp'])
                }
            else:
                # For other events (DOM snapshots, mutations, etc.), use the data as is
                normalized_event = {
                    'type': event_type,
                    'data': event_data.get('data', event_data),  # Use 'data' property or fallback to whole event
                    'timestamp': event_data.get('timestamp', event['timestamp'])
                }
            
            events_data.append(normalized_event)


            # Use the original DOM snapshot and ensure it's first
            # Find the DOM snapshot in the events and move it to the beginning
            dom_snapshot_index = None
            for i, event in enumerate(events_data):
                if event['type'] == 2:
                    dom_snapshot_index = i
                    break
            
            if dom_snapshot_index is not None and dom_snapshot_index > 0:
                # Move DOM snapshot to the beginning
                dom_snapshot = events_data.pop(dom_snapshot_index)
                events_data.insert(0, dom_snapshot)
            
            # Check if the DOM snapshot has content, if not, try to find a better one
            first_dom_snapshot = events_data[0] if events_data and events_data[0]['type'] == 2 else None
            if first_dom_snapshot:
                dom_data = first_dom_snapshot.get('data', {})
                node_data = dom_data.get('node', {})
                
                # Check if node_data is a dictionary and has childNodes
                if isinstance(node_data, dict) and node_data.get('childNodes'):
                    html_node = node_data['childNodes'][0] if node_data['childNodes'] else None
                    if html_node and html_node.get('childNodes'):
                        body_node = html_node['childNodes'][0] if html_node['childNodes'] else None
                        if body_node and not body_node.get('childNodes'):
                            # Look for other DOM snapshots with content
                            better_snapshot_found = False
                            for i, event in enumerate(events_data[1:], 1):  # Skip first one
                                if event['type'] == 2:
                                    event_dom_data = event.get('data', {})
                                    event_node_data = event_dom_data.get('node', {})
                                    
                                    # Check if event_node_data is a dictionary and has childNodes
                                    if isinstance(event_node_data, dict) and event_node_data.get('childNodes'):
                                        event_html = event_node_data['childNodes'][0] if event_node_data['childNodes'] else None
                                        if event_html and event_html.get('childNodes'):
                                            event_body = event_html['childNodes'][0] if event_html['childNodes'] else None
                                            if event_body and event_body.get('childNodes'):
                                                # Replace the first snapshot with this better one
                                                events_data[0] = event
                                                events_data[i] = first_dom_snapshot
                                                better_snapshot_found = True
                                                break
                            

            

        
        # Calculate tab duration
        if events_list:
            start_time = events_list[0]['timestamp']
            end_time = events_list[-1]['timestamp']
            duration = end_time - start_time
        else:
            start_time = 0
            end_time = 0
            duration = 0
        
        # Replace external URLs with proxy URLs in the events data
        base_url = next((event.get('page_url') for event in events_list if event.get('page_url')), None)
        events_data = replace_urls_with_proxy(events_data, base_url=base_url)
        
        result['tabs'][tab_id] = {
            'events': events_data,
            'start_time': start_time,
            'end_time': end_time,
            'duration': duration,
            'event_count': len(events_data)
        }
        

    
    return result

def tab_labels():
    """
    Generator function to get 'A', 'B', 'AA', 'AB'...
    """
    n = 1
    while True:
        num = n
        label = ""
        while num > 0:
            num, rem = divmod(num - 1, 26)
            label = chr(65 + rem) + label
        yield label
        n += 1

def update_human_tabs(human_tab_dict, tab_id, gen):
    """
    It adds a human-readable name of a tab like 'A', 'B', ... 'AA', 'AB'...
    """
    if tab_id not in human_tab_dict:
        human_tab_dict[tab_id] =  next(gen)


def _notify_memory_checkpoint(memory_callback, stage, **details):
    if memory_callback is None:
        return
    try:
        memory_callback(stage, **details)
    except Exception:
        pass


def get_consolidated_timeline_data(request, session_id, allowed_project_ids=None, memory_callback=None):
    """Get one rrweb stream plus its independent analytical control timeline."""
    session, events = get_session_and_events(
        request,
        session_id,
        allowed_project_ids=allowed_project_ids,
    )
    
    # Valid rrweb event types for timeline
    valid_rrweb_types = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14}
    
    # Process all events chronologically
    consolidated_events = []
    tab_switches = []
    human_tab_dict = dict()
    label_generator =tab_labels()
    session_start_time = None
    current_activity_tab = None
    first_activity_tab = None
    first_replay_tab = None
    first_page_url = None
    

    # Sort all events by timestamp
    sorted_events = sorted(events, key=lambda e: get_timestamp_for_sorting(e.data))
    _notify_memory_checkpoint(memory_callback, 'after_db_load', db_event_count=len(sorted_events))
    
    print(f"Processing {len(sorted_events)} events for session {session_id}")
    
    # Build consolidated timeline with proper tab switch events
    for event in sorted_events:
        event_data = event.data
        
        # Skip invalid rrweb events
        if not is_valid_rrweb_event(event_data, valid_rrweb_types):
            continue

        if first_page_url is None and event.url:
            first_page_url = event.url
            
        tab_id = event.tab_id or 'unknown'
        timestamp = get_timestamp_for_sorting(event_data)
        if first_replay_tab is None:
            first_replay_tab = tab_id
        
        # Use the first event timestamp as session start time
        if session_start_time is None:
            session_start_time = timestamp
        
        # Calculate relative timestamp
        relative_timestamp = timestamp - session_start_time if session_start_time else 0

        try:
            activity_event_type = int(event_data.get('type'))
        except (TypeError, ValueError):
            activity_event_type = None
        nested_event_data = event_data.get('data', {})
        if not isinstance(nested_event_data, dict):
            nested_event_data = {}
        raw_source = nested_event_data.get('source') if activity_event_type == 3 else None
        try:
            activity_source = int(raw_source)
        except (TypeError, ValueError):
            activity_source = None
        is_tab_activity = activity_event_type == 3 and activity_source in {1, 2, 5}
        if is_tab_activity:
            if first_activity_tab is None:
                first_activity_tab = tab_id
                update_human_tabs(human_tab_dict, tab_id, label_generator)
            if current_activity_tab is not None and tab_id != current_activity_tab:
                tab_switches.append({
                    'from_tab': current_activity_tab,
                    'to_tab': tab_id,
                    'timestamp': relative_timestamp,
                    'absolute_timestamp': timestamp
                })
                update_human_tabs(human_tab_dict, current_activity_tab, label_generator)
                update_human_tabs(human_tab_dict, tab_id, label_generator)
            current_activity_tab = tab_id
        
        # Normalize event for rrweb player
        event_type = event_data.get('type', 0)
        
        if event_type == 3:  # Input events
            normalized_event = {
                'type': event_type,
                'data': event_data.get('data', {}),
                'timestamp': relative_timestamp
            }
        else:
            normalized_event = {
                'type': event_type,
                'data': event_data.get('data', event_data),
                'timestamp': relative_timestamp
            }
        
        consolidated_events.append(normalized_event)
    
    # Ensure we have a DOM snapshot at the beginning
    if consolidated_events and consolidated_events[0]['type'] != 2:
        # Look for the first DOM snapshot
        dom_snapshot = None
        for event in consolidated_events:
            if event['type'] == 2:
                dom_snapshot = event
                break
        
        if dom_snapshot:
            # Move DOM snapshot to the beginning
            consolidated_events.remove(dom_snapshot)
            consolidated_events.insert(0, dom_snapshot)
    
    # Sort events by timestamp to ensure proper order
    consolidated_events.sort(key=lambda x: x['timestamp'])
    replay_available = any(map(is_replayable_full_snapshot, consolidated_events))

    # Replace external URLs with proxy URLs in consolidated events
    consolidated_events = replace_urls_with_proxy(consolidated_events, base_url=first_page_url)
    replay_duration_ms = int(round(max(
        (event.get('timestamp', 0) for event in consolidated_events),
        default=0,
    )))
    replay_duration_ms = max(0, replay_duration_ms)
    project = getattr(getattr(session, 'visitor', None), 'project', None)
    analytics_timeline = build_analytics_replay_timeline(
        project,
        session,
    )
    analytics_duration_ms = max(
        0,
        int(analytics_timeline.get('durationMs') or 0),
    )
    _notify_memory_checkpoint(
        memory_callback,
        'after_consolidate',
        replay_event_count=len(consolidated_events),
        tab_switch_count=len(tab_switches),
        analytics_segment_count=len(analytics_timeline['segments']),
    )
    
    print(f"Consolidated {len(consolidated_events)} events, {len(tab_switches)} tab switches")
    initial_tab = first_activity_tab or first_replay_tab or 'unknown'
    update_human_tabs(human_tab_dict, initial_tab, label_generator)
    print(f"First activity tab: {first_activity_tab}, Initial tab ID: {initial_tab}")

    return {
        'events': consolidated_events,
        'tab_switches': tab_switches,
        'human_tab_dict': human_tab_dict,
        'total_duration': analytics_duration_ms,
        'rrweb_duration': replay_duration_ms,
        'session_start_time': session_start_time,
        'initial_tab_id': initial_tab,
        'analytics_timeline': analytics_timeline,
        'replay_available': replay_available,
        'replay_unavailable_reason': (
            '' if replay_available else 'missing_full_snapshot'
        ),
    }


