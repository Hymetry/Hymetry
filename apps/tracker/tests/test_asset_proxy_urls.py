from copy import deepcopy
import os
from unittest.mock import patch
from urllib.parse import urlencode

from django.test import SimpleTestCase

from apps.tracker.tools import replace_urls_with_proxy


@patch.dict(os.environ, {'HYMETRY_DOMAIN': 'https://alpha.hymetry.com'})
class AssetProxyUrlTests(SimpleTestCase):
    def proxy_url(self, original_url):
        return f"https://alpha.hymetry.com/asset-proxy?{urlencode({'url': original_url})}"

    def test_proxy_url_encodes_resource_query_string(self):
        events = [
            {
                'type': 2,
                'data': {
                    'node': {
                        'type': 2,
                        'tagName': 'link',
                        'attributes': {
                            'href': 'https://customer.example.com/assets/app.css?v=1&theme=dark',
                        },
                    },
                },
            },
        ]

        result = replace_urls_with_proxy(deepcopy(events))

        self.assertEqual(
            result[0]['data']['node']['attributes']['href'],
            self.proxy_url('https://customer.example.com/assets/app.css?v=1&theme=dark'),
        )

    def test_proxy_resolves_recorded_page_relative_resources(self):
        events = [
            {
                'type': 4,
                'data': {
                    'href': 'https://customer.example.com/work_packages/123',
                },
                'timestamp': 0,
            },
            {
                'type': 2,
                'data': {
                    'node': {
                        'type': 2,
                        'tagName': 'link',
                        'attributes': {
                            'href': '/assets/main.css?v=1&theme=dark',
                        },
                    },
                },
                'timestamp': 1,
            },
        ]

        result = replace_urls_with_proxy(deepcopy(events))

        self.assertEqual(
            result[1]['data']['node']['attributes']['href'],
            self.proxy_url('https://customer.example.com/assets/main.css?v=1&theme=dark'),
        )

    def test_proxy_resolves_relative_css_urls_inside_inlined_styles(self):
        events = [
            {
                'type': 4,
                'data': {
                    'href': 'https://customer.example.com/projects/alpha/',
                },
                'timestamp': 0,
            },
            {
                'type': 2,
                'data': {
                    'node': {
                        'type': 2,
                        'tagName': 'style',
                        'attributes': {
                            '_cssText': (
                                ".logo{background:url('/img/logo.svg?v=1&mode=dark')}"
                                "@import url(/assets/chunk.css?x=1&y=2);"
                            ),
                        },
                    },
                },
                'timestamp': 1,
            },
        ]

        result = replace_urls_with_proxy(deepcopy(events))
        css_text = result[1]['data']['node']['attributes']['_cssText']

        self.assertIn("url('/img/logo.svg?v=1&mode=dark')", css_text)
        self.assertIn(
            f'url("{self.proxy_url("https://customer.example.com/assets/chunk.css?x=1&y=2")}")',
            css_text,
        )

    def test_proxy_does_not_rewrite_script_or_svg_resources(self):
        events = [
            {
                'type': 4,
                'data': {
                    'href': 'https://customer.example.com/projects/alpha/',
                },
                'timestamp': 0,
            },
            {
                'type': 2,
                'data': {
                    'node': {
                        'type': 2,
                        'tagName': 'script',
                        'attributes': {
                            'src': '/assets/app.js',
                        },
                    },
                },
                'timestamp': 1,
            },
            {
                'type': 2,
                'data': {
                    'node': {
                        'type': 2,
                        'tagName': 'img',
                        'attributes': {
                            'src': '/img/logo.svg',
                        },
                    },
                },
                'timestamp': 2,
            },
        ]

        result = replace_urls_with_proxy(deepcopy(events))

        self.assertEqual(result[1]['data']['node']['attributes']['src'], '/assets/app.js')
        self.assertEqual(result[2]['data']['node']['attributes']['src'], '/img/logo.svg')

    def test_style_preloads_become_stylesheets_for_replay(self):
        events = [
            {
                'type': 4,
                'data': {
                    'href': 'https://customer.example.com/projects/alpha/',
                },
                'timestamp': 0,
            },
            {
                'type': 2,
                'data': {
                    'node': {
                        'type': 2,
                        'tagName': 'link',
                        'attributes': {
                            'rel': 'preload',
                            'as': 'style',
                            'href': '/assets/application.css?v=1',
                            'onload': "this.onload=null;this.rel='stylesheet'",
                        },
                    },
                },
                'timestamp': 1,
            },
        ]

        result = replace_urls_with_proxy(deepcopy(events))
        attributes = result[1]['data']['node']['attributes']

        self.assertEqual(attributes['rel'], 'stylesheet')
        self.assertNotIn('as', attributes)
        self.assertNotIn('onload', attributes)
        self.assertEqual(
            attributes['href'],
            self.proxy_url('https://customer.example.com/assets/application.css?v=1'),
        )

    def test_fallback_base_url_resolves_relative_assets_without_meta_event(self):
        events = [
            {
                'type': 2,
                'data': {
                    'node': {
                        'type': 2,
                        'tagName': 'link',
                        'attributes': {
                            'href': '/assets/main.css',
                        },
                    },
                },
            },
        ]

        result = replace_urls_with_proxy(
            deepcopy(events),
            base_url='https://customer.example.com/work_packages/123',
        )

        self.assertEqual(
            result[0]['data']['node']['attributes']['href'],
            self.proxy_url('https://customer.example.com/assets/main.css'),
        )
