from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse


class ClosedAuthenticationTests(TestCase):
    def test_public_signup_and_email_reset_routes_do_not_exist(self):
        for path in (
            '/accounts/signup/',
            '/sign-up/',
            '/accounts/password/reset/',
            '/password/reset/request/',
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_local_email_login_works_without_sending_email(self):
        get_user_model().objects.create_superuser(
            username='admin@example.com',
            email='admin@example.com',
            password='another-secure-password-123',
        )
        get_user_model().objects.create_user(
            username='owner@example.com',
            email='owner@example.com',
            password='a-secure-password-123',
        )

        response = self.client.post(
            reverse('sign_in'),
            {'username': 'OWNER@example.com', 'password': 'a-secure-password-123'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    def test_profile_sign_out_uses_post_and_clears_session(self):
        User = get_user_model()
        User.objects.create_superuser(
            username='admin@example.com',
            email='admin@example.com',
            password='another-secure-password-123',
        )
        user = User.objects.create_user(
            username='owner@example.com',
            email='owner@example.com',
            password='a-secure-password-123',
        )
        self.client.force_login(user)

        profile = self.client.get(reverse('users:user_profile'))
        sign_out_url = reverse('sign_out')
        self.assertContains(profile, f'action="{sign_out_url}"')
        self.assertContains(profile, 'method="post"')

        response = self.client.post(sign_out_url)

        self.assertRedirects(response, reverse('sign_in'))
        self.assertNotIn('_auth_user_id', self.client.session)
