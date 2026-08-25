from django.apps import AppConfig


class TrackerConfig(AppConfig):
    name = 'apps.tracker'

    def ready(self):
        # Connects the Visits scope signal handlers for row-at-a-time writers.
        from apps.tracker import visits_scope  # noqa: F401
