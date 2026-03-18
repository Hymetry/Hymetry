import json
import re
from collections import defaultdict
from django.utils import timezone
from urllib.parse import urlparse, urljoin

from apps.tracker.models import Session
from config.runtime_url_values import runtime_urls


def get_session_only(request, session_id):
    """Get authorized session without querying events."""
    user_projects = request.user.projectmembership_set.values_list('project', flat=True)
    session = Session.objects.select_related('visitor__project').get(
        session_id=session_id,
        visitor__project__in=user_projects
    )
    return session

def replace_urls_with_proxy(events_data):
    """
    Replace external resource URLs in events data with CloudFlare proxy URLs.
    This function processes the events data and replaces external resource URLs
    (CSS, JS, images, fonts, etc.) with CloudFlare proxy URLs to solve CORS issues.
    """
    if isinstance(events_data, str):
        events_data = json.loads(events_data)
    domain_url = runtime_urls.get_hymetry_domain()
    
    def replace_urls_in_object(obj):
        """Recursively replace URLs in an object."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, str):
                    # Check if it's a direct URL
                    if is_external_resource_url(value):
                        obj[key] = create_proxy_url(value)
                    # Check if it contains any external resource URLs (CSS, HTML, or plain text)
                    elif contains_external_resource_urls(value):
                        obj[key] = replace_urls_in_text(value)
                elif isinstance(value, (dict, list)):
                    replace_urls_in_object(value)
        elif isinstance(obj, list):
            for item in obj:
                replace_urls_in_object(item)
    
    def is_external_resource_url(url):
        """Check if URL is an external resource that should be proxied."""
        if not url or not isinstance(url, str):
            return False
        
        # Skip data URLs, relative URLs, and our own domain
        if url.startswith('data:') or url.startswith('blob:') or url.startswith('#'):
            return False
        
        if url.startswith('/'):
            return False
        
        try:
            parsed = urlparse(url)
            # Only proxy http/https URLs
            if parsed.scheme not in ['http', 'https']:
                return False
            
            # Don't proxy our own domain
            app_domain = urlparse(domain_url).netloc
            own_domains = [app_domain, 'localhost', '127.0.0.1']
            if parsed.netloc in own_domains:
                return False
            
            # Check if it's a resource URL that should be proxied
            return is_resource_url(url)
        except:
            return False
    
    def is_resource_url(url):
        """Check if URL is a web resource that should be proxied."""
        if not url:
            return False
        
        # Resource file extensions to proxy
        resource_extensions = {
            # Stylesheets
            '.css', '.scss', '.sass', '.less',
            # JavaScript
            '.js', '.mjs', '.jsx', '.ts', '.tsx',
            # Images
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.ico',
            # Fonts
            '.woff', '.woff2', '.ttf', '.otf', '.eot',
            # Media
            '.mp4', '.webm', '.ogg', '.mp3', '.wav', '.avi', '.mov',
            # Documents
            '.pdf', '.doc', '.docx', '.xls', '.xlsx',
            # Archives
            '.zip', '.rar', '.tar', '.gz',
            # Other common resources
            '.xml', '.json', '.txt', '.csv'
        }
        
        # Check file extension
        url_lower = url.lower()
        for ext in resource_extensions:
            if url_lower.endswith(ext):
                return True
        
        # Check for common resource patterns in URLs
        resource_patterns = [
            r'\.(css|js|png|jpg|jpeg|gif|svg|woff|woff2|ttf|otf|mp4|webm|pdf)',
            r'/(css|js|images|img|assets|static|media|fonts)/',
            r'\.(googleapis\.com|gstatic\.com|cloudflare\.com|jsdelivr\.net|unpkg\.com)',
            r'\.(cdn|static|assets|media)\.',
            r'/api/',
            r'\.(min|bundle|vendor)\.(css|js)',
        ]
        
        import re
        for pattern in resource_patterns:
            if re.search(pattern, url_lower, re.IGNORECASE):
                return True
        
        return False
    
    def create_proxy_url(original_url):
        """Create an asset proxy URL."""
        return f"{domain_url}/asset-proxy?url={original_url}"
    
    def contains_external_resource_urls(text):
        """Check if text contains any external resource URLs."""
        if not isinstance(text, str):
            return False
        # Look for common resource URL patterns
        url_patterns = [
            r'url\(["\']?[^"\')\s]+["\']?\)',  # CSS url() declarations
            r'@import\s+["\'][^"\']+["\']',  # CSS @import statements
            r'src=["\'][^"\']+["\']',  # HTML src attributes
            r'href=["\'][^"\']+["\']',  # HTML href attributes
            r'data-src=["\'][^"\']+["\']',  # HTML data-src attributes
        ]
        import re
        for pattern in url_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                # Extract the URL from the match
                if pattern == r'url\(["\']?[^"\')\s]+["\']?\)':
                    # Extract URL from url() declaration
                    url_match = re.search(r'url\(["\']?([^"\')\s]+)["\']?\)', match)
                    if url_match:
                        url = url_match.group(1).strip('"\'')
                        if is_external_resource_url(url):
                            return True
                elif pattern == r'@import\s+["\'][^"\']+["\']':
                    # Extract URL from @import statement
                    import_match = re.search(r'@import\s+["\']([^"\']+)["\']', match)
                    if import_match:
                        url = import_match.group(1)
                        if is_external_resource_url(url):
                            return True
                elif pattern in [r'src=["\'][^"\']+["\']', r'href=["\'][^"\']+["\']', r'data-src=["\'][^"\']+["\']']:
                    # Extract URL from HTML attributes
                    attr_match = re.search(r'["\']([^"\']+)["\']', match)
                    if attr_match:
                        url = attr_match.group(1)
                        if is_external_resource_url(url):
                            return True
        return False
    
    def replace_urls_in_text(text):
        """Replace resource URLs in any text content with proxy URLs."""
        if not isinstance(text, str):
            return text
        
        import re
        
        # Replace URLs in CSS url() declarations
        def replace_css_url(match):
            url_content = match.group(1)
            url_content = url_content.strip('"\'')
            if is_external_resource_url(url_content):
                return f'url("{create_proxy_url(url_content)}")'
            return match.group(0)
        
        # Replace URLs in CSS @import statements
        def replace_css_import(match):
            import_url = match.group(1)
            if is_external_resource_url(import_url):
                return f'@import "{create_proxy_url(import_url)}"'
            return match.group(0)
        
        # Replace URLs in HTML attributes
        def replace_html_url(match):
            attr_name = match.group(1)
            url_content = match.group(2)
            if is_external_resource_url(url_content):
                return f'{attr_name}="{create_proxy_url(url_content)}"'
            return match.group(0)
        
        # Apply all replacements
        text = re.sub(r'url\(["\']?([^"\')\s]+)["\']?\)', replace_css_url, text)
        text = re.sub(r'@import\s+["\']([^"\']+)["\']', replace_css_import, text)
        text = re.sub(r'(src|href|data-src)=["\']([^"\']+)["\']', replace_html_url, text)
        
        return text
    
    # Process the events data
    replace_urls_in_object(events_data)
    
    return events_data


def get_session_and_events(request, session_id):
    """Get session and events data with optimized queries."""
    user_projects = request.user.projectmembership_set.values_list('project', flat=True)
    session = Session.objects.select_related('visitor__project').get(
        session_id=session_id, 
        visitor__project__in=user_projects
    )
    events = session.events.select_related('page').order_by('timestamp')
    return session, events


def is_valid_rrweb_event(event_data, valid_types=None):
    """Check if event is a valid rrweb event."""
    if valid_types is None:
        # Default valid rrweb event types: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14
        valid_types = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14}
    
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


def get_pages_data(request, session_id):
    session, events = get_session_and_events(request, session_id)
    events_data = [event.data for event in events]

    # Filter out non-rrweb events and sort by timestamp
    if events_data:
        # Filter events to only include valid rrweb events
        events_data = [event for event in events_data if is_valid_rrweb_event(event)]
        
        # Sort events by timestamp
        events_data.sort(key=get_timestamp_for_sorting)
        
        # Replace external URLs with proxy URLs
        events_data = replace_urls_with_proxy(events_data)

    return json.dumps(events_data, indent=2).replace('</', '<\\/')


def get_tab_timeline_data(request, session_id):
    """Get timeline data for multi-tab recording playback."""
    session, events = get_session_and_events(request, session_id)
    
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
            'db_timestamp': event.timestamp.isoformat()
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
        events_data = replace_urls_with_proxy(events_data)
        
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


def get_consolidated_timeline_data(request, session_id):
    """Get consolidated timeline data for single rrweb player with all tabs combined."""
    session, events = get_session_and_events(request, session_id)
    
    # Valid rrweb event types for timeline
    valid_rrweb_types = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14}
    
    # Process all events chronologically
    consolidated_events = []
    tab_switches = []
    human_tab_dict = dict()
    label_generator =tab_labels()
    session_start_time = None
    current_tab = None
    first_tab = None  # Track the first tab separately
    

    # Sort all events by timestamp
    sorted_events = sorted(events, key=lambda e: get_timestamp_for_sorting(e.data))
    
    print(f"Processing {len(sorted_events)} events for session {session_id}")
    
    # Build consolidated timeline with proper tab switch events
    for event in sorted_events:
        event_data = event.data
        
        # Skip invalid rrweb events
        if not is_valid_rrweb_event(event_data, valid_rrweb_types):
            continue
            
        tab_id = event.tab_id or 'unknown'
        timestamp = get_timestamp_for_sorting(event_data)
        
        # Use the first event timestamp as session start time
        if session_start_time is None:
            session_start_time = timestamp
        
        # Track the first tab we encounter
        if first_tab is None:
            update_human_tabs(human_tab_dict, tab_id, label_generator)
            first_tab = tab_id
        
        # Calculate relative timestamp
        relative_timestamp = timestamp - session_start_time if session_start_time else 0
        
        # Check for tab switch
        if current_tab is not None and tab_id != current_tab:
            # Add tab switch to list
            tab_switches.append({
                'from_tab': current_tab,
                'to_tab': tab_id,
                'timestamp': relative_timestamp,
                'absolute_timestamp': timestamp
            })
            update_human_tabs(human_tab_dict, current_tab, label_generator)
            update_human_tabs(human_tab_dict, tab_id, label_generator)

        current_tab = tab_id
        
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

    # Replace external URLs with proxy URLs in consolidated events
    consolidated_events = replace_urls_with_proxy(consolidated_events)
    
    print(f"Consolidated {len(consolidated_events)} events, {len(tab_switches)} tab switches")
    print(f"First tab: {first_tab}, Initial tab ID: {first_tab if first_tab else 'unknown'}")

    return {
        'events': consolidated_events,
        'tab_switches': tab_switches,
        'human_tab_dict': human_tab_dict,
        'total_duration': 0,
        'session_start_time': session_start_time,
        'initial_tab_id': first_tab if first_tab else 'unknown',
    }


