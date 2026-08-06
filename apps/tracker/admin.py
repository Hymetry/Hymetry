import csv
import json
from types import MethodType

from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from apps.tracker.models import (
    AnalyticsEvent,
    AnalyticsSession,
    BubbleCache,
    COMMON_OPENAI_CHAT_MODELS,
    Event,
    LLMUsageLog,
    ProjectPageNamingRun,
    ProjectPageRule,
    ProjectPageRuleVersion,
    SafeInputRegexTemplate,
    Session,
    TitlePrompt,
    Visitor,
)


ANALYTICS_EVENT_ADMIN_FIELDS = tuple(field.name for field in AnalyticsEvent._meta.fields)


class SuggestedModelsTextInput(forms.TextInput):
    def __init__(self, suggestions, *args, list_id, **kwargs):
        self.suggestions = tuple(suggestions)
        self.list_id = list_id
        attrs = kwargs.setdefault('attrs', {})
        attrs['list'] = self.list_id
        super().__init__(*args, **kwargs)

    def render(self, name, value, attrs=None, renderer=None):
        input_html = super().render(name, value, attrs=attrs, renderer=renderer)
        datalist_html = format_html(
            '<datalist id="{}">{}</datalist>',
            self.list_id,
            format_html_join(
                '',
                '<option value="{}"></option>',
                ((model_name,) for model_name in self.suggestions),
            ),
        )
        return format_html('{}{}', input_html, datalist_html)


class TitlePromptAdminForm(forms.ModelForm):
    bootstrap_page_naming_openai_model = forms.CharField(
        max_length=100,
        label='OpenAI model name for bootstrap page naming prompt',
        help_text='Type any model name or choose one of the suggested OpenAI models.',
        required=False,
        widget=SuggestedModelsTextInput(
            COMMON_OPENAI_CHAT_MODELS,
            list_id='bootstrap-page-naming-openai-models',
            attrs={'placeholder': 'gpt-5.4'},
        ),
    )
    hourly_unstable_openai_model = forms.CharField(
        max_length=100,
        label='OpenAI model name for hourly unstable prompt',
        help_text='Type any model name or choose one of the suggested OpenAI models.',
        widget=SuggestedModelsTextInput(
            COMMON_OPENAI_CHAT_MODELS,
            list_id='hourly-unstable-openai-models',
            attrs={'placeholder': 'gpt-5.4-mini'},
        ),
    )
    daily_stable_openai_model = forms.CharField(
        max_length=100,
        label='OpenAI model name for daily stable prompt',
        help_text='Type any model name or choose one of the suggested OpenAI models.',
        widget=SuggestedModelsTextInput(
            COMMON_OPENAI_CHAT_MODELS,
            list_id='daily-stable-openai-models',
            attrs={'placeholder': 'gpt-5.4-mini'},
        ),
    )

    class Meta:
        model = TitlePrompt
        fields = '__all__'


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
            inactivity_end = reference_time + timezone.timedelta(
                seconds=settings.SESSION_EXPIRATION_SECONDS
            )
            maximum_end = obj.start_time + timezone.timedelta(
                seconds=max(1, int(getattr(settings, 'SESSION_MAX_DURATION_SECONDS', 43200)))
            )
            is_active = timezone.now() < min(inactivity_end, maximum_end)
        
        if is_active:
            return format_html('<span style="color: {};">● {}</span>', 'green', 'Active')
        else:
            return format_html('<span style="color: {};">● {}</span>', 'red', 'Inactive')

    is_active_display.short_description = 'Status'

    def event_count(self, obj):
        # Use annotated count instead of obj.events.count() to avoid additional query
        return getattr(obj, 'cached_event_count', 0)

    event_count.short_description = 'Events'


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'url', 'session', 'tab_id', 'timestamp', 'data_preview')
    list_filter = ('event_type', 'timestamp', 'session__visitor__project')
    search_fields = ('url', 'session__session_id')
    readonly_fields = ('timestamp',)
    date_hierarchy = 'timestamp'

    def data_preview(self, obj):
        if obj.data:
            data_str = str(obj.data)
            return data_str[:50] + "..." if len(data_str) > 50 else data_str
        return "No data"

    data_preview.short_description = 'Data Preview'


@admin.register(AnalyticsSession)
class AnalyticsSessionAdmin(admin.ModelAdmin):
    list_display = ('session_id', 'project', 'visitor_guid', 'user_id', 'company_id', 'start_time', 'last_activity', 'ended_at')
    list_filter = ('project', 'start_time', 'last_activity', 'ended_at')
    readonly_fields = ('session_id',)
    date_hierarchy = 'start_time'


@admin.register(AnalyticsEvent)
class AnalyticsEventAdmin(admin.ModelAdmin):
    list_display = ANALYTICS_EVENT_ADMIN_FIELDS
    list_filter = ('event_type', 'timestamp', 'session__project')
    readonly_fields = ('timestamp',)
    date_hierarchy = 'timestamp'

    def get_readonly_fields(self, request, obj=None):
        if obj is not None:
            return ('session', *self.readonly_fields)
        return self.readonly_fields


@admin.register(BubbleCache)
class BubbleCacheAdmin(admin.ModelAdmin):
    list_display = ('url', 'session', 'timestamp', 'size', 'clicks', 'mouse_moves', 'key_strokes', 'seconds_spent',
                    'project')
    list_filter = ('timestamp', 'session__visitor__project')
    search_fields = ('url', 'session__session_id')
    readonly_fields = ('timestamp',)
    date_hierarchy = 'timestamp'

    def project(self, obj):
        if obj.session and obj.session.visitor:
            return obj.session.visitor.project
        return None

    project.short_description = 'Project'

    def get_readonly_fields(self, request, obj=None):
        if obj is not None:
            return ('session', *self.readonly_fields)
        return self.readonly_fields


@admin.register(TitlePrompt)
class TitlePromptAdmin(admin.ModelAdmin):
    form = TitlePromptAdminForm
    list_display = ('name', 'updated_at')
    search_fields = (
        'name',
        'bootstrap_page_naming_prompt',
        'bootstrap_page_naming_openai_model',
        'hourly_unstable_prompt',
        'hourly_unstable_openai_model',
        'daily_stable_prompt',
        'daily_stable_openai_model',
    )
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (None, {'fields': ('name',)}),
        (
            'Page Naming Prompts',
            {
                'fields': (
                    'bootstrap_page_naming_prompt',
                    'bootstrap_page_naming_openai_model',
                    'hourly_unstable_prompt',
                    'hourly_unstable_openai_model',
                    'daily_stable_prompt',
                    'daily_stable_openai_model',
                )
            },
        ),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )

    def has_add_permission(self, request):
        if TitlePrompt.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(ProjectPageRule)
class ProjectPageRuleAdmin(admin.ModelAdmin):
    change_list_template = 'admin/tracker/projectpagerule/change_list.html'
    list_display = ('project', 'product_area', 'product_area_short_name', 'page_name', 'pattern', 'priority', 'is_active', 'created_by', 'updated_at')
    list_filter = ('project', 'is_active', 'created_by')
    search_fields = ('project__name', 'product_area', 'product_area_short_name', 'page_name', 'pattern')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('project', 'priority', 'product_area', 'page_name')

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'export-csv/',
                self.admin_site.admin_view(self.export_csv_view),
                name='tracker_projectpagerule_export_csv',
            ),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        export_csv_url = reverse('admin:tracker_projectpagerule_export_csv')
        query_string = request.GET.urlencode()
        if query_string:
            export_csv_url = f'{export_csv_url}?{query_string}'
        extra_context['export_csv_url'] = export_csv_url
        return super().changelist_view(request, extra_context=extra_context)

    def export_csv_view(self, request):
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied

        changelist = self.get_changelist_instance(request)
        queryset = changelist.get_queryset(request).select_related('project')

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        timestamp = timezone.localtime(timezone.now()).strftime('%Y%m%d_%H%M%S')
        response['Content-Disposition'] = f'attachment; filename="project_page_rules_{timestamp}.csv"'
        response.write('\ufeff')

        writer = csv.writer(response)
        writer.writerow([
            'id',
            'project_id',
            'project_name',
            'product_area',
            'product_area_short_name',
            'page_name',
            'pattern',
            'priority',
            'is_active',
            'created_by',
            'created_at',
            'updated_at',
        ])

        for rule in queryset.iterator():
            writer.writerow([
                rule.id,
                rule.project_id,
                rule.project.name if rule.project else '',
                rule.product_area,
                rule.product_area_short_name,
                rule.page_name,
                rule.pattern,
                rule.priority,
                rule.is_active,
                rule.created_by,
                rule.created_at.isoformat() if rule.created_at else '',
                rule.updated_at.isoformat() if rule.updated_at else '',
            ])

        return response


@admin.register(ProjectPageNamingRun)
class ProjectPageNamingRunAdmin(admin.ModelAdmin):
    list_display = (
        'project',
        'mode',
        'phase',
        'status',
        'prompt_name',
        'prompt_version',
        'new_urls_1h',
        'new_urls_24h',
        'output_rules_count',
        'started_at',
    )
    list_filter = ('mode', 'phase', 'status', 'project')
    search_fields = ('project__name', 'skip_reason', 'error_message', 'prompt_name')
    readonly_fields = ('started_at', 'finished_at')
    ordering = ('-started_at',)


@admin.register(LLMUsageLog)
class LLMUsageLogAdmin(admin.ModelAdmin):
    list_display = (
        'created_at',
        'feature',
        'project',
        'mode',
        'model_name',
        'result',
        'duration_ms',
        'page_naming_run',
    )
    list_filter = ('feature', 'result', 'mode', 'model_name', 'project', 'created_at')
    search_fields = ('project__name', 'prompt_name', 'prompt_version', 'error_message')
    readonly_fields = tuple(field.name for field in LLMUsageLog._meta.fields)
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)


@admin.register(ProjectPageRuleVersion)
class ProjectPageRuleVersionAdmin(admin.ModelAdmin):
    list_display = ('project', 'mode', 'phase', 'run', 'created_at')
    list_filter = ('project', 'mode', 'phase', 'created_at')
    search_fields = ('project__name', 'run__prompt_name')
    readonly_fields = ('created_at', 'rules_json_pretty', 'ai_response_json_pretty')

    def rules_json_pretty(self, obj):
        return format_html('<pre>{}</pre>', json.dumps(obj.rules_json, indent=2, ensure_ascii=False))

    rules_json_pretty.short_description = 'Rules JSON'

    def ai_response_json_pretty(self, obj):
        return format_html('<pre>{}</pre>', json.dumps(obj.ai_response_json, indent=2, ensure_ascii=False))

    ai_response_json_pretty.short_description = 'AI Response JSON'


@admin.register(SafeInputRegexTemplate)
class SafeInputRegexTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'the_order', 'enabled', 'pattern', 'description')


ANALYTICS_ADMIN_MODEL_ORDER = {
    'AnalyticsEvent': 1,
    'AnalyticsSession': 2,
    'ProjectPageRule': 3,
    'ProjectPageRuleVersion': 4,
    'ProjectPageNamingRun': 5,
    'LLMUsageLog': 6,
}
_original_get_app_list = admin.site.get_app_list


def _get_app_list_with_analytics_section(self, request, app_label=None):
    if app_label is not None:
        return _original_get_app_list(request, app_label)

    app_list = _original_get_app_list(request, app_label)
    analytics_models = []
    filtered_app_list = []

    for app in app_list:
        app_copy = app.copy()
        app_models = []
        for model in app['models']:
            if model['object_name'] in ANALYTICS_ADMIN_MODEL_ORDER:
                analytics_models.append(model)
            else:
                app_models.append(model)

        if app_models:
            app_copy['models'] = app_models
            filtered_app_list.append(app_copy)

    if analytics_models:
        analytics_models.sort(key=lambda model: ANALYTICS_ADMIN_MODEL_ORDER.get(model['object_name'], 999))
        filtered_app_list.insert(
            0,
            {
                'name': 'Analytics',
                'app_label': 'analytics',
                'app_url': reverse('admin:index'),
                'has_module_perms': True,
                'models': analytics_models,
            },
        )

    return filtered_app_list


admin.site.get_app_list = MethodType(_get_app_list_with_analytics_section, admin.site)
