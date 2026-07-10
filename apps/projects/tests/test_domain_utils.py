from types import SimpleNamespace

from django.test import RequestFactory, SimpleTestCase

from apps.projects.domain_utils import (
    extract_registered_domain,
    host_matches_allowed_domain,
    normalize_allowed_domains,
    normalize_workspace_website_url,
    request_matches_allowed_domains,
)


class DomainUtilsTests(SimpleTestCase):
    def test_extract_registered_domain_uses_public_suffix_list(self):
        cases = {
            'acme.com.ua': 'acme.com.ua',
            'app.acme.com.ua': 'acme.com.ua',
            'https://app.acme.com.ua/dashboard': 'acme.com.ua',
            'www.example.co.uk': 'example.co.uk',
            'customer.github.io': 'customer.github.io',
            'foo.vercel.app': 'foo.vercel.app',
        }

        for raw_value, expected_domain in cases.items():
            with self.subTest(raw_value=raw_value):
                self.assertEqual(extract_registered_domain(raw_value), expected_domain)
                self.assertEqual(normalize_allowed_domains([raw_value]), [expected_domain])

    def test_extract_registered_domain_rejects_public_suffix_only_values(self):
        for raw_value in ('', '   ', 'com.ua', 'co.uk', 'github.io', 'vercel.app', '[', 'https://acme.com:bad'):
            with self.subTest(raw_value=raw_value):
                self.assertEqual(extract_registered_domain(raw_value), '')
                self.assertEqual(normalize_allowed_domains([raw_value]), [])

    def test_host_matches_allowed_domain_includes_subdomains(self):
        self.assertTrue(host_matches_allowed_domain('https://app.acme.com.ua/dashboard', 'acme.com.ua'))
        self.assertTrue(host_matches_allowed_domain('www.customer.github.io', 'customer.github.io'))
        self.assertFalse(host_matches_allowed_domain('https://other.com.ua/dashboard', 'acme.com.ua'))
        self.assertFalse(host_matches_allowed_domain('https://github.io/dashboard', 'customer.github.io'))

    def test_request_matches_allowed_domains_uses_project_allowed_domains_only(self):
        request = RequestFactory().post(
            '/analytics',
            HTTP_ORIGIN='https://workspace-only.com',
            HTTP_REFERER='https://workspace-only.com/page',
        )
        project = SimpleNamespace(allowed_domains=['acme.com.ua'])

        self.assertTrue(
            request_matches_allowed_domains(
                request,
                project,
                candidate_url='https://app.acme.com.ua/dashboard',
            )
        )
        self.assertFalse(
            request_matches_allowed_domains(
                request,
                project,
                candidate_url='https://workspace-only.com/dashboard',
            )
        )

    def test_workspace_website_url_keeps_trimmed_user_value(self):
        self.assertEqual(
            normalize_workspace_website_url('  https://app.acme.com.ua/dashboard  '),
            'https://app.acme.com.ua/dashboard',
        )
        self.assertEqual(normalize_workspace_website_url(' App.Acme.com/path '), 'App.Acme.com/path')
        self.assertEqual(normalize_workspace_website_url('qqqqq'), 'qqqqq')
        self.assertEqual(normalize_workspace_website_url('['), '')
