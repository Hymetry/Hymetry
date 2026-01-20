from apps.tracker.models import Session
from apps.tracker.tools import get_pages_data, get_tab_timeline_data
from apps.tracker.all_sessions_bubbles_view import AllSessionsBubblesView


def get_event_description(event):
    """Generate human-readable description for an event."""
    event_type = event.get('type')
    data = event.get('data', {})
    
    # rrweb event type mapping
    RRWEB_EVENT_TYPES = {
        0: 'DomContent',
        1: 'DomSnapshot', 
        2: 'FullSnapshot',
        3: 'Incremental',
        4: 'Meta',
        5: 'Custom',
        6: 'Plugin',
    }
    
    # rrweb IncrementalSource mapping (for type 3 events)
    INCREMENTAL_SOURCE = {
        0: 'Mutation',
        1: 'MouseMove',
        2: 'MouseInteraction',
        3: 'Scroll',
        4: 'ViewportResize',
        5: 'Input',
        6: 'MediaInteraction',
        7: 'StyleSheetRule',
        8: 'CanvasMutation',
        9: 'Font',
        10: 'Log',
        12: 'Drag',
        14: 'TextSelection',
    }
    
    # MouseInteraction types (for type 3, source 2)
    MOUSE_INTERACTIONS = {
        0: 'MouseUp',
        1: 'MouseDown',
        2: 'Click',
        3: 'ContextMenu',
        4: 'DblClick',
        5: 'Focus',
        6: 'Blur',
        7: 'TouchStart',
        8: 'TouchEnd',
        9: 'TouchMove',
    }
    
    desc = RRWEB_EVENT_TYPES.get(event_type, f'UnknownType({event_type})')
    
    # For type 3 (Incremental), get source
    if event_type == 3:
        source = data.get('source')
        desc = INCREMENTAL_SOURCE.get(source, f'UnknownSource({source})')
        # For MouseInteraction, get sub-type
        if source == 2:
            mouse_type = data.get('type')
            desc = f'MouseInteraction: {MOUSE_INTERACTIONS.get(mouse_type, mouse_type)}'
        # For Input, show input value
        if source == 5:
            value = data.get('text', '')
            desc = f'Input: "{value}"'
    
    # For type 4 (Meta), check for navigation
    if event_type == 4:
        href = data.get('href', '')
        desc = f'Page navigation to {href}'
    
    return desc


class RecordingViewMixin:
    """Common functionality for recording views."""
    
    def __init__(self, request, project_id, session_id):
        self.request = request
        self.project_id = project_id
        self.session_id = session_id
    
    def get_session_data(self):
        """Get basic session and events data."""
        session = Session.objects.get(session_id=self.session_id)
        events_json = get_pages_data(self.request, self.session_id)
        tab_timeline_data = get_tab_timeline_data(self.request, self.session_id)
        return session, events_json, tab_timeline_data
    
    def get_bubble_data(self, session):
        """Get bubble data for session visualization."""
        # Reuse AllSessionsBubblesView to get consistent color mapping
        view_instance = AllSessionsBubblesView(self.request, self.project_id)
        
        # Set the selected date to match this session's date
        from datetime import date
        session_date = session.start_time.date()
        view_instance.selected_date = session_date
        
        # Get all sessions for the same day to calculate global legend
        all_sessions_for_day = view_instance._get_sessions_for_day()
        
        # Use only cached bubble data (do not calculate in-memory)
        from apps.tracker.bubble_cache_manager import BubbleCacheManager
        all_session_ids = [s.session_id for s in all_sessions_for_day]
        all_session_cache, all_cached_entries = BubbleCacheManager.get_cached_bubbles_for_sessions(all_session_ids)
        
        # Calculate global legend from all cached data (same as recordings())
        overall_legend_pages = BubbleCacheManager.calculate_legend_from_cache(all_cached_entries)
        title_to_color = {item['page_title']: item['color'] for item in overall_legend_pages if not item['is_other']}
        
        # Get cached bubble data for this specific session
        session_cache = {self.session_id: all_session_cache.get(self.session_id, [])}
        
        # Process session bubbles using the exact same technique as recordings view
        session_data = view_instance._process_session_bubbles(
            [session],
            session_cache,
            title_to_color
        )
        
        # Get the processed bubbles for this session
        session_bubbles_data = session_data[0]['bubbles'] if session_data else []
        return session_bubbles_data
    
    def get_flat_events(self, tab_timeline_data):
        """Get flat events for timeline view (only used by recording_with_timeline)."""
        flat_events = []
        if tab_timeline_data and 'tabs' in tab_timeline_data:
            for tab_id, tab_data in tab_timeline_data['tabs'].items():
                for event in tab_data['events']:
                    # Add human-readable description
                    event_with_desc = {
                        'timestamp': event.get('timestamp', 0),
                        'type': event.get('type'),
                        'data': event.get('data', {}),
                        'tab_id': tab_id,
                        'description': get_event_description(event)
                    }
                    flat_events.append(event_with_desc)
        
        # Sort by timestamp
        flat_events.sort(key=lambda e: e['timestamp'])
        flat_events = flat_events[:-1]

        # Calculate relative timestamps for JavaScript comparison
        if flat_events:
            baseline_timestamp = flat_events[0]['timestamp']
            for event in flat_events:
                # Keep original absolute timestamp for display
                event['absolute_timestamp'] = event['timestamp']
                # Calculate relative timestamp (milliseconds from first event)
                event['relative_timestamp'] = event['timestamp'] - baseline_timestamp
                # Update timestamp to be relative for JavaScript
                event['timestamp'] = event['relative_timestamp']
        
        return flat_events 