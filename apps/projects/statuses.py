from django.utils import timezone


PROJECT_STATUS_BADGE_CLASSES = {
    'setup_required': 'border border-amber-200 bg-amber-100 text-amber-800',
    'active': 'border border-sky-200 bg-sky-50 text-sky-700',
    'no_recent_data': 'border border-slate-300 bg-white text-slate-700',
}

PROJECT_RECENT_DATA_DAYS = 7


def project_effective_status(project):
    if not project.first_production_event_at or not project.allowed_domains:
        return 'setup_required'
    if project.last_event_at and project.last_event_at < timezone.now() - timezone.timedelta(days=PROJECT_RECENT_DATA_DAYS):
        return 'no_recent_data'
    return project.status if project.status in PROJECT_STATUS_BADGE_CLASSES else 'active'


def project_status_label(project):
    labels = {
        'setup_required': 'Setup required',
        'active': 'Active',
        'no_recent_data': 'No recent data',
    }
    return labels.get(project_effective_status(project), 'Setup required')


def project_status_badge_class(project):
    return PROJECT_STATUS_BADGE_CLASSES.get(project_effective_status(project), PROJECT_STATUS_BADGE_CLASSES['setup_required'])
