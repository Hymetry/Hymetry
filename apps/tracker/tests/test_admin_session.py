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
