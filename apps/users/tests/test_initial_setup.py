from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class InitialAdminSetupTests(TestCase):
    def test_sign_in_redirects_to_setup_until_admin_exists(self):
        response = self.client.get(reverse('sign_in'))

        self.assertRedirects(response, reverse('users:initial_admin_setup'))

    def test_setup_requires_no_environment_token(self):
        response = self.client.post(
            reverse('users:initial_admin_setup'),
            {
                'email': 'admin@example.com',
                'password': 'a-secure-password-123',
                'password_confirm': 'a-secure-password-123',
                'terms': 'on',
            },
        )

        self.assertRedirects(response, reverse('projects:project_list'))
        self.assertTrue(get_user_model().objects.filter(is_superuser=True).exists())

    def test_setup_creates_exactly_one_admin_and_seals_endpoint(self):
        response = self.client.post(
            reverse('users:initial_admin_setup'),
            {
                'email': 'ADMIN@example.com',
                'password': 'a-secure-password-123',
                'password_confirm': 'a-secure-password-123',
                'terms': 'on',
            },
        )

        self.assertRedirects(response, reverse('projects:project_list'))
        admin = get_user_model().objects.get(is_superuser=True)
        self.assertEqual(admin.email, 'admin@example.com')
        self.assertEqual(get_user_model().objects.filter(is_superuser=True).count(), 1)
        self.assertEqual(self.client.get(reverse('users:initial_admin_setup')).status_code, 302)

    def test_password_policy_error_preserves_email_and_terms_but_clears_passwords(self):
        response = self.client.post(
            reverse('users:initial_admin_setup'),
            {
                'email': 'admin@example.com',
                'password': 'short',
                'password_confirm': 'short',
                'terms': 'on',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'too short')
        self.assertContains(response, 'value="admin@example.com"')
        self.assertContains(response, 'id="terms"')
        self.assertContains(response, 'checked')
        self.assertNotContains(response, 'value="short"')
        self.assertFalse(get_user_model().objects.filter(is_superuser=True).exists())

    def test_password_mismatch_preserves_email_and_terms_but_clears_passwords(self):
        response = self.client.post(
            reverse('users:initial_admin_setup'),
            {
                'email': 'owner@example.com',
                'password': 'a-secure-password-123',
                'password_confirm': 'different-secure-password-123',
                'terms': 'on',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'passwords do not match')
        self.assertContains(response, 'value="owner@example.com"')
        self.assertContains(response, 'checked')
        self.assertNotContains(response, 'value="a-secure-password-123"')
        self.assertNotContains(response, 'value="different-secure-password-123"')
        self.assertFalse(get_user_model().objects.filter(is_superuser=True).exists())

    def test_terms_error_preserves_email_and_clears_passwords(self):
        response = self.client.post(
            reverse('users:initial_admin_setup'),
            {
                'email': 'owner@example.com',
                'password': 'a-secure-password-123',
                'password_confirm': 'a-secure-password-123',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Accept the license terms')
        self.assertContains(response, 'value="owner@example.com"')
        self.assertNotContains(response, 'value="a-secure-password-123"')
        self.assertFalse(get_user_model().objects.filter(is_superuser=True).exists())
