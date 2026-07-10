from django.contrib import admin
from django.contrib import messages

from .services import restore_project, restore_workspace
from .models import (
    Project,
    Workspace,
    WorkspaceMembership,
)
from apps.tracker.page_naming import reset_project_page_naming_to_bootstrap


@admin.action(description='Restore selected archived workspaces')
def restore_selected_workspaces(modeladmin, request, queryset):
    for workspace in queryset:
        restore_workspace(workspace)


@admin.action(description='Restore selected archived projects')
def restore_selected_projects(modeladmin, request, queryset):
    for project in queryset:
        restore_project(project)


@admin.action(description='Reset selected projects to page naming bootstrap')
def reset_selected_projects_page_naming_to_bootstrap(modeladmin, request, queryset):
    totals = {
        'projects': 0,
        'rules_deactivated': 0,
        'events_reset': 0,
        'generated_product_areas_deleted': 0,
    }

    for project in queryset:
        result = reset_project_page_naming_to_bootstrap(project)
        totals['projects'] += 1
        totals['rules_deactivated'] += result['rules_deactivated']
        totals['events_reset'] += result['events_reset']
        totals['generated_product_areas_deleted'] += result['generated_product_areas_deleted']

    messages.success(
        request,
        (
            'Page naming reset to bootstrap for {projects} project(s). '
            'Deactivated {rules_deactivated} active rule(s), reset {events_reset} analytics event(s), '
            'and deleted {generated_product_areas_deleted} generated product area(s). '
            'Analytics cache rows were left unchanged.'
        ).format(**totals),
    )


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = (
        'public_id',
        'name',
        'website_url',
        'created_by',
        'archived_at',
        'delete_after',
        'created_at',
    )
    list_filter = ('created_at', 'archived_at')
    search_fields = ('=public_id', 'name', 'website_url', 'created_by__email')
    readonly_fields = ('public_id',)
    actions = (restore_selected_workspaces,)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'slug',
        'workspace',
        'status',
        'lifecycle_status',
        'created_by',
        'product_url',
        'allowed_domains',
        'first_production_event_at',
        'last_event_at',
        'page_naming_state',
        'page_naming_first_event_at',
        'page_naming_state_changed_at',
        'archived_at',
        'delete_after',
        'created_at',
    )
    list_filter = ('status', 'lifecycle_status', 'page_naming_state', 'created_at')
    search_fields = ('name', 'slug', 'workspace__name', 'created_by__email', 'product_url')
    readonly_fields = ('page_naming_first_event_at', 'page_naming_state_changed_at')
    actions = (restore_selected_projects, reset_selected_projects_page_naming_to_bootstrap)


@admin.register(WorkspaceMembership)
class WorkspaceMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'workspace', 'role', 'status', 'created_at', 'removed_at')
    list_filter = ('role', 'status', 'created_at')
    search_fields = ('user__email', 'workspace__name')
