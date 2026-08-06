from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase


class PasswordPolicyValidatorTests(SimpleTestCase):
    def test_password_length_boundaries(self):
        with self.assertRaises(ValidationError):
            validate_password("a" * (settings.PASSWORD_MIN_LENGTH - 1))

        validate_password("a" * settings.PASSWORD_MIN_LENGTH)
        validate_password("a" * settings.PASSWORD_MAX_LENGTH)

        with self.assertRaises(ValidationError):
            validate_password("a" * (settings.PASSWORD_MAX_LENGTH + 1))
