from django.contrib import admin

from .models import Project, ProjectMembership


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'created_at')


@admin.register(ProjectMembership)
class ProjectMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'project', 'is_owner', 'joined_at')
