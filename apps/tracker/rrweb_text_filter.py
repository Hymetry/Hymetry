"""
RRWeb Text Filter - Redis Stateful Masking
Filters sensitive data from rrweb events using regex patterns and Redis-based stateful masking.
"""

from typing import Dict, List, Optional
import re2

from apps.tracker.models import SafeInputRegexTemplate
from .redis_stateful_masking import generate_field_id, secure_mask_text_redis


def get_pattern_rules() -> List[Dict]:
    """Get regex patterns and masking rules from database with pre-compiled patterns"""
    try:
        rules = []
        for template in SafeInputRegexTemplate.objects.filter(enabled=True).order_by('the_order'):
            try:
                # Pre-compile the regex pattern
                compiled_pattern = re2.compile(template.pattern)
                rules.append({
                    'name': template.name,
                    'pattern': template.pattern,
                    'compiled_pattern': compiled_pattern,  # Store pre-compiled pattern
                    'keep_prefix_chars': template.keep_prefix_chars,
                    'keep_prefix_digits': template.keep_prefix_digits,
                    'hide_after_delimiter': template.hide_after_delimiter,
                    'mask_type': template.mask_type,
                })
            except re2.error as e:
                print(f"Invalid regex pattern '{template.pattern}' in rule '{template.name}': {e}")
                # Skip invalid patterns instead of failing entirely
                continue
        return rules
    except Exception as e:
        print(f"Error loading pattern rules: {e}")
        return []


def mask_with_digit_prefix(text: str, keep_digits: int) -> str:
    """
    Mask text keeping first N digits visible, preserving delimiters
    
    Args:
        text: Input text
        keep_digits: Number of digits to keep visible
    
    Returns:
        Masked text
    """
    result = []
    digits_shown = 0
    
    for char in text:
        if char.isdigit():
            if digits_shown < keep_digits:
                result.append(char)
                digits_shown += 1
            else:
                result.append('*')
        else:
            # Preserve delimiters and + symbol
            if char in ['-', ' ', '.', '(', ')', '@', '+']:
                result.append(char)
            else:
                result.append('*')
    
    return ''.join(result)


def mask_with_char_prefix(text: str, keep_chars: int) -> str:
    """
    Mask text keeping first N characters visible
    
    Args:
        text: Input text
        keep_chars: Number of characters to keep visible
    
    Returns:
        Masked text
    """
    if len(text) <= keep_chars:
        return text
    
    # Show prefix, mask rest
    prefix = text[:keep_chars]
    masked = '*' * (len(text) - keep_chars)
    return prefix + masked


def mask_with_delimiter(text: str, delimiter: str) -> str:
    """
    Mask text hiding everything after the specified delimiter
    
    Args:
        text: Input text
        delimiter: Delimiter character to hide everything after
    
    Returns:
        Masked text
    """
    if not delimiter or delimiter not in text:
        return text
    
    # Find the delimiter position
    delimiter_pos = text.find(delimiter)
    
    # Show everything up to and including the delimiter, mask the rest
    visible_part = text[:delimiter_pos + 1]
    hidden_part = text[delimiter_pos + 1:]
    
    return visible_part + '*' * len(hidden_part)


def apply_progressive_masking(text: str, rule: Dict) -> str:
    """
    Apply progressive masking based on pattern match
    
    Args:
        text: Input text to mask
        rule: Pattern rule configuration
    
    Returns:
        Masked text
    """
    keep_digits = rule.get('keep_prefix_digits', 0)
    keep_chars = rule.get('keep_prefix_chars', 0)
    hide_after_delimiter = rule.get('hide_after_delimiter')
    mask_type = rule.get('mask_type', 'custom')
    
    # Handle custom mask type (legacy support)
    if mask_type == 'custom':
        if hide_after_delimiter:
            return mask_with_delimiter(text, hide_after_delimiter)
        elif keep_digits > 0:
            return mask_with_digit_prefix(text, keep_digits)
        elif keep_chars > 0:
            return mask_with_char_prefix(text, keep_chars)
        else:
            return '*' * len(text)
    
    # Handle new mask types
    if keep_digits > 0:
        return mask_with_digit_prefix(text, keep_digits)
    elif keep_chars > 0:
        return mask_with_char_prefix(text, keep_chars)
    elif hide_after_delimiter:
        return mask_with_delimiter(text, hide_after_delimiter)
    else:
        return '*' * len(text)


def secure_mask_text_dynamic(text: str, field_id: Optional[str] = None, session_id: str = None, visitor_id: str = None, page_url: str = None) -> str:
    """
    Redis stateful masking - eliminates show/hide effects by maintaining field state
    
    Args:
        text: Current text to mask
        field_id: Field identifier (if provided, uses Redis stateful masking)
        session_id: Session ID for field identification
        visitor_id: Visitor ID for field identification  
        page_url: Page URL for field identification
    
    Returns:
        Masked text
    """
    if not text or not text.strip():
        return text

    # If we have all required parameters for stateful masking, use Redis
    if field_id and session_id and visitor_id and page_url:
        try:
            # Generate proper field ID
            redis_field_id = generate_field_id(session_id, visitor_id, page_url, field_id)
            return secure_mask_text_redis(text, redis_field_id)
        except Exception as e:
            print(f"Error in Redis stateful masking: {e}")
            # Fall back to stateless masking
    
    # Fallback to stateless masking
    rules = get_pattern_rules()
    if not rules:
        return text

    # Try each pattern in order (most specific first)
    for rule in rules:
        try:
            # Use pre-compiled pattern instead of compiling each time
            compiled_pattern = rule['compiled_pattern']
            
            # Check if pattern matches
            if compiled_pattern.search(text):
                return apply_progressive_masking(text, rule)
                
        except Exception as e:
            print(f"Error processing rule {rule.get('name', 'unknown')}: {e}")
            continue
    
    # No pattern matched - return original text
    return text


def mask_rrweb_event(event_data: Dict, session_id: str = None, visitor_id: str = None, page_url: str = None) -> Dict:
    """
    Mask sensitive data in rrweb event data using comprehensive event type analysis.
    Incorporates deep analysis logic from filter_sensitive_data() while preserving
    Redis stateful masking for input events.
    
    Args:
        event_data: rrweb event data dictionary
        session_id: Session ID for Redis stateful masking
        visitor_id: Visitor ID for Redis stateful masking
        page_url: Page URL for Redis stateful masking
    
    Returns:
        Masked event data
    """
    if not isinstance(event_data, dict):
        return event_data

    # Create a copy to avoid modifying original
    masked_event = event_data.copy()
    
    # Get event type and data for comprehensive analysis
    event_type = event_data.get('type')
    data = event_data.get('data', {})

    # Comprehensive event type handling (integrated from filter_sensitive_data)
    
    # Case 1: Input Events (Type 3, Source 5) - Primary source of sensitive data
    # Use Redis stateful masking for these events
    if event_type == 3 and isinstance(data, dict) and data.get('source') == 5:
        if 'text' in data:
            field_identifier = _extract_field_identifier(event_data)
            
            # Use Redis stateful masking if we have all required parameters
            if session_id and visitor_id and page_url and field_identifier:
                masked_event['data'] = data.copy()
                masked_event['data']['text'] = secure_mask_text_dynamic(
                    data['text'],
                    field_id=field_identifier,
                    session_id=session_id,
                    visitor_id=visitor_id,
                    page_url=page_url
                )
            else:
                # Fall back to stateless masking
                masked_event['data'] = data.copy()
                masked_event['data']['text'] = secure_mask_text_dynamic(data['text'])

    # Case 2: DOM Snapshots (Type 2) - Contains form values in attributes
    elif event_type == 2 and isinstance(data, dict):
        masked_event['data'] = _filter_dom_snapshot(data)

    # Case 3: DOM Mutations (Type 3, Source 0) - Contains new form values
    elif event_type == 3 and isinstance(data, dict) and data.get('source') == 0:
        masked_event['data'] = _filter_dom_mutation(data)

    # Case 4: Text Selection Events (Type 3, Source 14)
    elif event_type == 3 and isinstance(data, dict) and data.get('source') == 14:
        if 'text' in data:
            masked_event['data'] = data.copy()
            masked_event['data']['text'] = secure_mask_text_dynamic(data['text'])

    # Case 5: Custom Events (Type 5) - May contain sensitive payload
    elif event_type == 5 and isinstance(data, dict):
        if 'payload' in data:
            masked_event['data'] = data.copy()
            masked_event['data']['payload'] = secure_mask_text_dynamic(data['payload'])

    # Case 6: Meta Events (Type 4) - URLs that might contain sensitive query params
    elif event_type == 4 and isinstance(data, dict):
        if 'href' in data:
            masked_event['data'] = data.copy()
            masked_event['data']['href'] = secure_mask_text_dynamic(data['href'])

    
    return masked_event


def _extract_field_identifier(event_data: Dict) -> str:
    """
    Extract field identifier from rrweb event data
    
    Args:
        event_data: rrweb event data dictionary
    
    Returns:
        Field identifier string
    """
    if not isinstance(event_data, dict) or 'data' not in event_data:
        return "unknown_field"
    
    data = event_data['data']
    
    # Try to extract field identifier from various sources
    if 'id' in data:
        return f"#{data['id']}"
    elif 'name' in data:
        return f"[name='{data['name']}']"
    elif 'tagName' in data and 'id' in data:
        return f"{data['tagName'].lower()}#{data['id']}"
    elif 'tagName' in data and 'className' in data:
        return f"{data['tagName'].lower()}.{data['className'].split(' ')[0]}"
    else:
        # Fallback to a generic identifier
        return f"input_{hash(str(data)) % 10000}"


def clear_field_states():
    """Clear all field states (useful for testing or reset)"""
    # This is now handled by Redis cleanup
    pass


def get_field_state(field_id: str) -> str:
    """Get current state of a specific field"""
    # This is now handled by Redis
    return ""


def reset_field_state(field_id: str):
    """Reset state of a specific field"""
    # This is now handled by Redis
    pass


def filter_sensitive_data(data):
    """
    Filter sensitive data from event data using regex patterns from SafeInputRegexTemplate.
    Replaces matched patterns with '*'.

    Args:
        data: The data to filter (can be string, dict, or any JSON-serializable object)

    Returns:
        The filtered data with sensitive patterns replaced by '*'
    """
    if isinstance(data, str):
        return secure_mask_text_dynamic(data)
    elif isinstance(data, dict):
        return _filter_dict(data)
    else:
        return data

def _filter_dict(data_dict):
    """
    Filter sensitive data from dictionary using switch-like logic for specific rrweb event types.
    Targets primary sources of sensitive text data.

    Args:
        data_dict: Dictionary to filter

    Returns:
        Filtered dictionary
    """
    if not isinstance(data_dict, dict):
        return data_dict

    filtered_dict = data_dict.copy()

    # Switch-like logic for different event types and sources
    event_type = data_dict.get('type')
    data = data_dict.get('data', {})

    # Case 1: Input Events (Type 3, Source 5) - Primary source of sensitive data
    if event_type == 3 and isinstance(data, dict) and data.get('source') == 5:
        if 'text' in data:
            filtered_dict['data'] = data.copy()
            filtered_dict['data']['text'] = secure_mask_text_dynamic(data['text'])

    # Case 2: DOM Snapshots (Type 2) - Contains form values in attributes
    elif event_type == 2 and isinstance(data, dict):
        filtered_dict['data'] = _filter_dom_snapshot(data)

    # Case 3: DOM Mutations (Type 3, Source 0) - Contains new form values
    elif event_type == 3 and isinstance(data, dict) and data.get('source') == 0:
        filtered_dict['data'] = _filter_dom_mutation(data)

    # Case 4: Text Selection Events (Type 3, Source 14)
    elif event_type == 3 and isinstance(data, dict) and data.get('source') == 14:
        if 'text' in data:
            filtered_dict['data'] = data.copy()
            filtered_dict['data']['text'] = secure_mask_text_dynamic(data['text'])

    # Case 5: Custom Events (Type 5) - May contain sensitive payload
    elif event_type == 5 and isinstance(data, dict):
        if 'payload' in data:
            filtered_dict['data'] = data.copy()
            filtered_dict['data']['payload'] = secure_mask_text_dynamic(data['payload'])

    # Case 6: Meta Events (Type 4) - URLs that might contain sensitive query params
    elif event_type == 4 and isinstance(data, dict):
        if 'href' in data:
            filtered_dict['data'] = data.copy()
            filtered_dict['data']['href'] = secure_mask_text_dynamic(data['href'])

    return filtered_dict


def _filter_dom_snapshot(data):
    """
    Filter sensitive data from DOM snapshot (Type 2 events).
    Targets form input values in node attributes.
    """
    if not isinstance(data, dict):
        return data

    filtered_data = data.copy()

    # Filter node attributes if present
    if 'node' in data and isinstance(data['node'], dict):
        filtered_data['node'] = _filter_node_attributes(data['node'])

    return filtered_data


def _filter_dom_mutation(data):
    """
    Filter sensitive data from DOM mutation (Type 3, Source 0 events).
    Targets new form values in adds/removes arrays.
    """
    if not isinstance(data, dict):
        return data

    filtered_data = data.copy()

    # Filter adds array
    if 'adds' in data and isinstance(data['adds'], list):
        filtered_data['adds'] = []
        for add_item in data['adds']:
            if isinstance(add_item, dict) and 'node' in add_item:
                filtered_add = add_item.copy()
                filtered_add['node'] = _filter_node_attributes(add_item['node'])
                filtered_data['adds'].append(filtered_add)
            else:
                filtered_data['adds'].append(add_item)

    # Filter removes array (less likely to contain sensitive data but for consistency)
    if 'removes' in data and isinstance(data['removes'], list):
        filtered_data['removes'] = []
        for remove_item in data['removes']:
            if isinstance(remove_item, dict) and 'node' in remove_item:
                filtered_remove = remove_item.copy()
                filtered_remove['node'] = _filter_node_attributes(remove_item['node'])
                filtered_data['removes'].append(filtered_remove)
            else:
                filtered_data['removes'].append(remove_item)

    return filtered_data


def _filter_node_attributes(node):
    """
    Filter sensitive data from node attributes, specifically targeting form input values.
    """
    if not isinstance(node, dict):
        return node

    filtered_node = node.copy()

    # Filter attributes if present
    if 'attributes' in node and isinstance(node['attributes'], dict):
        filtered_attributes = node['attributes'].copy()

        # Target specific sensitive attributes
        sensitive_attrs = ['value', 'data-value', 'placeholder', 'title', 'alt']
        for attr in sensitive_attrs:
            if attr in filtered_attributes:
                filtered_attributes[attr] = secure_mask_text_dynamic(filtered_attributes[attr])

        filtered_node['attributes'] = filtered_attributes

    # Recursively filter child nodes
    if 'childNodes' in node and isinstance(node['childNodes'], list):
        filtered_node['childNodes'] = []
        for child in node['childNodes']:
            filtered_node['childNodes'].append(_filter_node_attributes(child))

    return filtered_node