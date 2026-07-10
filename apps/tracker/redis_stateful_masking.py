"""
Redis-based stateful text masking implementation
"""
import redis
import hashlib
import json
from typing import Dict, List, Optional
from django.conf import settings
from django.core.cache import cache
import re2

from .models import SafeInputRegexTemplate


class RedisStatefulMaskingEngine:
    """Redis-based stateful masking engine"""

    def __init__(self, redis_url=None):
        self.redis_url = redis_url or getattr(settings, 'REDIS_URL', 'redis://localhost:6379/1')
        self.redis = redis.from_url(self.redis_url, decode_responses=True)
        self.pattern_rules = self._load_pattern_rules()
        self._setup_signal_handlers()
    
    def _load_pattern_rules(self) -> List[Dict]:
        """Load pattern rules from database with pre-compiled patterns"""
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
    
    def reload_pattern_rules(self):
        """Reload pattern rules from database (useful when patterns change)"""
        try:
            self.pattern_rules = self._load_pattern_rules()
            print(f"Reloaded {len(self.pattern_rules)} pattern rules")
        except Exception as e:
            print(f"Error reloading pattern rules: {e}")
    
    def _setup_signal_handlers(self):
        """Setup Django signals to reload patterns when SafeInputRegexTemplate changes"""
        try:
            from django.db.models.signals import post_save, post_delete
            from .models import SafeInputRegexTemplate
            
            # Connect signals to reload patterns
            post_save.connect(self._on_pattern_change, sender=SafeInputRegexTemplate)
            post_delete.connect(self._on_pattern_change, sender=SafeInputRegexTemplate)
        except Exception as e:
            print(f"Error setting up signal handlers: {e}")
    
    def _on_pattern_change(self, sender, **kwargs):
        """Signal handler called when SafeInputRegexTemplate changes"""
        self.reload_pattern_rules()
    
    def generate_field_id(self, session_id: str, visitor_id: str, page_url: str, field_identifier: str) -> str:
        """Generate unique field identifier"""
        # Normalize URL (remove query params, fragments, trailing slashes)
        normalized_url = page_url.split('?')[0].split('#')[0].rstrip('/')
        
        # Create composite identifier
        composite_id = f"{session_id}:{visitor_id}:{normalized_url}:{field_identifier}"
        
        # Generate hash (SHA-256, truncated to 16 chars for efficiency)
        field_id = hashlib.sha256(composite_id.encode()).hexdigest()[:16]
        
        return f"field_state:{session_id}:{field_id}"
    
    def _find_matching_pattern(self, text: str) -> Optional[Dict]:
        """Find the first matching pattern for the given text"""
        for rule in self.pattern_rules:
            try:
                # Use pre-compiled pattern instead of compiling each time
                compiled_pattern = rule['compiled_pattern']
                if compiled_pattern.search(text):
                    return rule
            except Exception as e:
                print(f"Error processing pattern {rule['name']}: {e}")
                continue
        return None
    
    def _apply_progressive_masking(self, text: str, rule: Dict) -> str:
        """Apply progressive masking based on rule"""
        keep_digits = rule.get('keep_prefix_digits', 0)
        keep_chars = rule.get('keep_prefix_chars', 0)
        hide_after_delimiter = rule.get('hide_after_delimiter')
        mask_type = rule.get('mask_type', 'custom')
        
        # Handle custom mask type (legacy support)
        if mask_type == 'custom':
            if hide_after_delimiter:
                # Hide everything after the specified delimiter
                if hide_after_delimiter not in text:
                    return text
                
                delimiter_pos = text.find(hide_after_delimiter)
                visible_part = text[:delimiter_pos + 1]
                hidden_part = text[delimiter_pos + 1:]
                return visible_part + '*' * len(hidden_part)
            elif keep_digits > 0:
                # Count digits and mask after keep_prefix_digits
                digits_shown = 0
                result = []
                for char in text:
                    if char.isdigit():
                        if digits_shown < keep_digits:
                            result.append(char)
                            digits_shown += 1
                        else:
                            result.append('*')
                    else:
                        if char in ['-', ' ', '.', '(', ')', '@', '+']:
                            result.append(char)
                        else:
                            result.append('*')
                return ''.join(result)
            elif keep_chars > 0:
                # Show first keep_chars characters
                if len(text) <= keep_chars:
                    return text
                else:
                    prefix = text[:keep_chars]
                    masked = '*' * (len(text) - keep_chars)
                    return prefix + masked
            else:
                return '*' * len(text)
        
        # Handle prefix_digits mask type
        elif mask_type == 'prefix_digits':
            if keep_digits > 0:
                # Count digits and mask after keep_prefix_digits
                digits_shown = 0
                result = []
                for char in text:
                    if char.isdigit():
                        if digits_shown < keep_digits:
                            result.append(char)
                            digits_shown += 1
                        else:
                            result.append('*')
                    else:
                        if char in ['-', ' ', '.', '(', ')', '@', '+']:
                            result.append(char)
                        else:
                            result.append('*')
                return ''.join(result)
            elif keep_chars > 0:
                # Show first keep_chars characters
                if len(text) <= keep_chars:
                    return text
                else:
                    prefix = text[:keep_chars]
                    masked = '*' * (len(text) - keep_chars)
                    return prefix + masked
            else:
                return '*' * len(text)
        
        # Handle new mask types
        if keep_digits > 0:
            # Count digits and mask after keep_prefix_digits
            digits_shown = 0
            result = []
            for char in text:
                if char.isdigit():
                    if digits_shown < keep_digits:
                        result.append(char)
                        digits_shown += 1
                    else:
                        result.append('*')
                else:
                    if char in ['-', ' ', '.', '(', ')', '@', '+']:
                        result.append(char)
                    else:
                        result.append('*')
            return ''.join(result)
        
        elif keep_chars > 0:
            # Show first keep_chars characters
            if len(text) <= keep_chars:
                return text
            else:
                prefix = text[:keep_chars]
                masked = '*' * (len(text) - keep_chars)
                return prefix + masked
        
        elif hide_after_delimiter:
            # Hide everything after the specified delimiter
            if hide_after_delimiter not in text:
                return text
            
            delimiter_pos = text.find(hide_after_delimiter)
            visible_part = text[:delimiter_pos + 1]
            hidden_part = text[delimiter_pos + 1:]
            return visible_part + '*' * len(hidden_part)
        
        else:
            return '*' * len(text)
    
    def secure_mask_text_stateful(self, text: str, field_id: str) -> str:
        """Stateful masking with Redis state storage"""
        if not text or not text.strip():
            # Clear state for empty text
            self.redis.delete(field_id)
            return text
        
        # Get previous masked text from Redis
        prev_masked = self.redis.get(field_id)
        
        if not prev_masked:
            # First time - apply normal masking
            matched_pattern = self._find_matching_pattern(text)
            if matched_pattern:
                masked_text = self._apply_progressive_masking(text, matched_pattern)
            else:
                # No pattern match - don't mask normal text
                masked_text = text
            
            # Store only masked text in Redis (no original storage)
            self.redis.set(field_id, masked_text)
            return masked_text
        
        # Continue with existing masking state - adjust length to match new text
        if len(text) != len(prev_masked):
            if len(text) > len(prev_masked):
                # Text extended - immediately apply masking to new characters
                # Find matching pattern for the new text first
                matched_pattern = self._find_matching_pattern(text)
                if matched_pattern:
                    # Apply masking to the entire new text
                    new_masked = self._apply_progressive_masking(text, matched_pattern)
                    # But preserve existing asterisks from Redis AND already-shown characters
                    result = []
                    for i in range(len(text)):
                        if i < len(prev_masked) and prev_masked[i] == '*':
                            # Keep asterisk from Redis (NEVER reveal)
                            result.append('*')
                        elif i < len(prev_masked) and prev_masked[i] != '*':
                            # Keep already-shown character (never hide it)
                            result.append(prev_masked[i])
                        else:
                            # Use new masking result for new characters
                            result.append(new_masked[i])
                    prev_masked = ''.join(result)
                else:
                    # No pattern matched - continue with existing behavior
                    if prev_masked and '*' in prev_masked:
                        # Continue masking new characters
                        new_chars = text[len(prev_masked):]
                        masked_new_chars = '*' * len(new_chars)
                        prev_masked = prev_masked + masked_new_chars
                    else:
                        # No previous masking - add new characters as-is
                        new_chars = text[len(prev_masked):]
                        prev_masked = prev_masked + new_chars
            else:
                # Text shortened - preserve existing masking pattern
                result = []
                for i in range(len(text)):
                    if i < len(prev_masked) and prev_masked[i] == '*':
                        # Keep asterisk from Redis (NEVER reveal)
                        result.append('*')
                    elif i < len(prev_masked) and prev_masked[i] != '*':
                        # Keep already-shown character (never hide it)
                        result.append(prev_masked[i])
                    else:
                        # New character (shouldn't happen in shortening, but just in case)
                        result.append(text[i])
                prev_masked = ''.join(result)
        
        # Update Redis with the result
        self.redis.set(field_id, prev_masked)
        return prev_masked
    
    def clear_field_state(self, field_id: str):
        """Clear state for a specific field"""
        self.redis.delete(field_id)
    
    def clear_session_states(self, session_id: str):
        """Clear all states for a session"""
        pattern = f"field_state:{session_id}:*"
        keys = self.redis.keys(pattern)
        if keys:
            self.redis.delete(*keys)
    
    def get_field_state(self, field_id: str) -> Optional[str]:
        """Get current field state"""
        return self.redis.get(field_id)
    
    def get_session_metrics(self, session_id: str) -> Dict:
        """Get metrics for a session"""
        pattern = f"field_state:{session_id}:*"
        keys = self.redis.keys(pattern)
        
        return {
            'session_id': session_id,
            'active_fields': len(keys),
            'field_keys': keys
        }


# Global instance for easy access
_redis_masking_engine = None

def get_redis_masking_engine():
    """Get or create Redis masking engine instance"""
    global _redis_masking_engine
    if _redis_masking_engine is None:
        _redis_masking_engine = RedisStatefulMaskingEngine()
    return _redis_masking_engine


def generate_field_id(session_id: str, visitor_id: str, page_url: str, field_identifier: str) -> str:
    """Generate field ID using the global engine"""
    engine = get_redis_masking_engine()
    return engine.generate_field_id(session_id, visitor_id, page_url, field_identifier)


def secure_mask_text_redis(text: str, field_id: str) -> str:
    """Main function for Redis-based stateful text masking"""
    engine = get_redis_masking_engine()
    return engine.secure_mask_text_stateful(text, field_id)


def cleanup_session_redis_data(session_id: str):
    """Clean up Redis data for a session - add to existing session close logic"""
    try:
        engine = get_redis_masking_engine()
        engine.clear_session_states(session_id)
    except Exception as e:
        # Log error but don't fail session close
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to cleanup Redis data for session {session_id}: {e}")
