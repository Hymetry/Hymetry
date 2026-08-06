from datetime import timedelta

from django.contrib import admin
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from apps.tracker.admin import SessionAdmin
from apps.tracker.models import Session


class SessionAdminTests(SimpleTestCase):
    @override_settings(SESSION_EXPIRATION_SECONDS=1800)
    def test_is_active_display_renders_active_status(self):
        model_admin = SessionAdmin(Session, admin.site)
        session = Session(last_activity=timezone.now())

        html = str(model_admin.is_active_display(session))

        self.assertIn('color: green;', html)
        self.assertIn('Active', html)

    @override_settings(SESSION_EXPIRATION_SECONDS=1800)
    def test_is_active_display_renders_inactive_status(self):
        model_admin = SessionAdmin(Session, admin.site)
        session = Session(last_activity=timezone.now() - timedelta(hours=2))

        html = str(model_admin.is_active_display(session))

        self.assertIn('color: red;', html)
        self.assertIn('Inactive', html)

    @override_settings(
        SESSION_EXPIRATION_SECONDS=1800,
        SESSION_MAX_DURATION_SECONDS=12 * 60 * 60,
    )
    def test_is_active_display_honors_absolute_maximum(self):
        model_admin = SessionAdmin(Session, admin.site)
        now = timezone.now()
        session = Session(
            start_time=now - timedelta(hours=12, seconds=1),
            last_activity=now,
        )

        html = str(model_admin.is_active_display(session))

        self.assertIn('color: red;', html)
        self.assertIn('Inactive', html)
