from django.contrib import admin
from django.utils.html import format_html

from apps.tracker.models import TitlePrompt, Page, OpenAIModel, Session, BubbleCache, Visitor, Event, \
    SafeInputRegexTemplate


@admin.register(Visitor)
class VisitorAdmin(admin.ModelAdmin):
    list_display = ('visitor_id', 'project', 'first_visit', 'last_activity', 'session_count')
    list_filter = ('project', 'first_visit', 'last_activity')
    readonly_fields = ('visitor_id',)

    def get_queryset(self, request):
        """Optimize queryset to avoid N+1 queries."""
        from django.db.models import Count
        
        return super().get_queryset(request).select_related(
            'project'  # Prefetch project in single query
        ).annotate(
            # Annotate session count to avoid individual COUNT queries
            cached_session_count=Count('sessions')
        )

    def session_count(self, obj):
        # Use annotated count instead of obj.sessions.count() to avoid additional query
        return getattr(obj, 'cached_session_count', 0)

    session_count.short_description = 'Sessions'


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('session_id', 'visitor', 'project', 'start_time', 'last_activity', 'ended_at', 'duration_display',
                    'is_active_display', 'event_count')
    list_filter = ('start_time', 'last_activity', 'ended_at', 'visitor__project')
    readonly_fields = ('session_id', 'duration_display')
    date_hierarchy = 'start_time'

    def get_queryset(self, request):
        """Optimize queryset to avoid N+1 queries by using select_related and annotations."""
        from django.db.models import Count, Max
        
        return super().get_queryset(request).select_related(
            'visitor__project'  # Prefetch visitor and project in single query
        ).annotate(
            # Annotate event count to avoid individual COUNT queries
            cached_event_count=Count('events'),
            # Annotate latest event timestamp to avoid individual MAX queries
            latest_event_timestamp=Max('events__timestamp')
        )

    def project(self, obj):
        # Now uses prefetched data, no additional query
        return obj.visitor.project if obj.visitor else None

    project.short_description = 'Project'

    def duration_display(self, obj):
        if obj.duration:
            total_seconds = int(obj.duration.total_seconds())
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return f"{minutes}m {seconds}s"
        return "N/A"

    duration_display.short_description = 'Duration'

    def is_active_display(self, obj):
        # Use annotated latest_event_timestamp to avoid additional query
        from django.conf import settings
        from django.utils import timezone
        
        # Use the annotated latest event timestamp if available
        last_event_ts = getattr(obj, 'latest_event_timestamp', None)
        reference_time = last_event_ts or obj.last_activity
        
        if not reference_time:
            is_active = False
        else:
            is_active = (timezone.now() - reference_time).total_seconds() < settings.SESSION_EXPIRATION_SECONDS
        
        if is_active:
            return format_html('<span style="color: green;">● Active</span>')
        else:
            return format_html('<span style="color: red;">● Inactive</span>')

    is_active_display.short_description = 'Status'

    def event_count(self, obj):
        # Use annotated count instead of obj.events.count() to avoid additional query
        return getattr(obj, 'cached_event_count', 0)

    event_count.short_description = 'Events'


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'page', 'session', 'tab_id', 'timestamp', 'data_preview')
    list_filter = ('event_type', 'timestamp', 'page', 'session__visitor__project')
    readonly_fields = ('timestamp',)
    date_hierarchy = 'timestamp'

    def data_preview(self, obj):
        if obj.data:
            data_str = str(obj.data)
            return data_str[:50] + "..." if len(data_str) > 50 else data_str
        return "No data"

    data_preview.short_description = 'Data Preview'


@admin.register(BubbleCache)
class BubbleCacheAdmin(admin.ModelAdmin):
    list_display = ('page', 'session', 'timestamp', 'size', 'clicks', 'mouse_moves', 'key_strokes', 'seconds_spent',
                    'project')
    list_filter = ('timestamp', 'page', 'session__visitor__project')
    readonly_fields = ('timestamp',)
    date_hierarchy = 'timestamp'

    def project(self, obj):
        if obj.session and obj.session.visitor:
            return obj.session.visitor.project
        return None

    project.short_description = 'Project'


@admin.register(TitlePrompt)
class TitlePromptAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')
    list_filter = ('is_active',)


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ('url', '_title', 'original_title', 'created_at')
    actions = ['clear_ai_title']

    def clear_ai_title(self, request, queryset):
        updated = queryset.update(_title="")
        self.message_user(request, f"Cleared AI titles for {updated} page(s).")

    clear_ai_title.short_description = 'Clear AI title (_title)'


@admin.register(OpenAIModel)
class OpenAIModelAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')
    list_editable = ('is_active',)
    list_filter = ('is_active',)


@admin.register(SafeInputRegexTemplate)
class SafeInputRegexTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'the_order', 'enabled', 'pattern', 'description')
