import socket
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.tracker.views import asset_proxy

PUBLIC_ADDRINFO = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]


class AssetProxyViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def proxy_url(self, original_url):
        return f"http://testserver/asset-proxy?{urlencode({'url': original_url})}"

    def upstream_response(self, body, content_type='text/css; charset=utf-8'):
        response = Mock()
        body_bytes = body.encode('utf-8')
        response.content = body_bytes
        response.iter_content.return_value = [body_bytes]
        response.status_code = 200
        response.headers = {'Content-Type': content_type}
        response.encoding = 'utf-8'
        response.is_redirect = False
        response.close = Mock()
        self.add_peer(response)
        return response

    def add_peer(self, response, peer_ip='93.184.216.34'):
        sock = Mock()
        sock.getpeername.return_value = (peer_ip, 443)
        connection = Mock()
        connection.sock = sock
        raw = Mock()
        raw._connection = connection
        response.raw = raw
        return response

    @patch('apps.tracker.views.socket.getaddrinfo', return_value=PUBLIC_ADDRINFO)
    @patch('apps.tracker.views.requests.get')
    def test_asset_proxy_rewrites_root_relative_css_font_urls(self, mock_get, mock_getaddrinfo):
        target_url = 'https://openproject.hymetry.com/assets/frontend/styles-EGU322HZ.css'
        mock_get.return_value = self.upstream_response(
            "@font-face{src:url('/media/openproject-icon-font-GUJZUFPS.woff2') format('woff2')}"
        )

        request = self.factory.get(f'/asset-proxy?{urlencode({"url": target_url})}')
        response = asset_proxy(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertIn(
            self.proxy_url('https://openproject.hymetry.com/media/openproject-icon-font-GUJZUFPS.woff2'),
            response.content.decode('utf-8'),
        )

    @patch('apps.tracker.views.socket.getaddrinfo', return_value=PUBLIC_ADDRINFO)
    @patch('apps.tracker.views.requests.get')
    def test_asset_proxy_rewrites_relative_css_urls_against_css_url(self, mock_get, mock_getaddrinfo):
        target_url = 'https://openproject.hymetry.com/assets/frontend/styles/app.css'
        mock_get.return_value = self.upstream_response(".logo{background:url('../images/logo.png')}")

        request = self.factory.get(f'/asset-proxy?{urlencode({"url": target_url})}')
        response = asset_proxy(request)

        self.assertIn(
            self.proxy_url('https://openproject.hymetry.com/assets/frontend/images/logo.png'),
            response.content.decode('utf-8'),
        )

    @patch('apps.tracker.views.socket.getaddrinfo', return_value=PUBLIC_ADDRINFO)
    @patch('apps.tracker.views.requests.get')
    def test_asset_proxy_does_not_rewrite_data_urls(self, mock_get, mock_getaddrinfo):
        target_url = 'https://openproject.hymetry.com/assets/frontend/styles.css'
        data_url = 'data:image/svg+xml;base64,PHN2Zw=='
        mock_get.return_value = self.upstream_response(f'.icon{{background:url("{data_url}")}}')

        request = self.factory.get(f'/asset-proxy?{urlencode({"url": target_url})}')
        response = asset_proxy(request)

        self.assertIn(data_url, response.content.decode('utf-8'))

    @patch('apps.tracker.views.socket.getaddrinfo', return_value=PUBLIC_ADDRINFO)
    @patch('apps.tracker.views.requests.get')
    def test_asset_proxy_does_not_rewrite_svg_urls(self, mock_get, mock_getaddrinfo):
        target_url = 'https://openproject.hymetry.com/assets/frontend/styles.css'
        mock_get.return_value = self.upstream_response(".logo{background:url('/img/logo.svg')}")

        request = self.factory.get(f'/asset-proxy?{urlencode({"url": target_url})}')
        response = asset_proxy(request)

        self.assertIn("url('/img/logo.svg')", response.content.decode('utf-8'))
        self.assertNotIn('/asset-proxy', response.content.decode('utf-8'))

    @patch('apps.tracker.views.socket.getaddrinfo', return_value=PUBLIC_ADDRINFO)
    @patch('apps.tracker.views.requests.get')
    def test_asset_proxy_leaves_non_css_assets_untouched(self, mock_get, mock_getaddrinfo):
        target_url = 'https://openproject.hymetry.com/media/font.woff2'
        mock_get.return_value = self.upstream_response('font-bytes', content_type='font/woff2')

        request = self.factory.get(f'/asset-proxy?{urlencode({"url": target_url})}')
        response = asset_proxy(request)

        self.assertEqual(response.content, b'font-bytes')

    @patch('apps.tracker.views.requests.get')
    def test_asset_proxy_blocks_loopback_urls_before_fetching(self, mock_get):
        target_url = 'http://127.0.0.1/admin/'

        request = self.factory.get(f'/asset-proxy?{urlencode({"url": target_url})}')
        response = asset_proxy(request)

        self.assertEqual(response.status_code, 403)
        mock_get.assert_not_called()

    @patch('apps.tracker.views.requests.get')
    def test_asset_proxy_blocks_carrier_grade_nat_urls_before_fetching(self, mock_get):
        target_url = 'http://100.64.0.1/admin/'

        request = self.factory.get(f'/asset-proxy?{urlencode({"url": target_url})}')
        response = asset_proxy(request)

        self.assertEqual(response.status_code, 403)
        mock_get.assert_not_called()

    @patch('apps.tracker.views.socket.getaddrinfo', return_value=PUBLIC_ADDRINFO)
    @patch('apps.tracker.views.requests.get')
    def test_asset_proxy_blocks_redirect_to_loopback_url(self, mock_get, mock_getaddrinfo):
        target_url = 'https://openproject.hymetry.com/assets/app.css'
        redirect_response = Mock()
        redirect_response.status_code = 302
        redirect_response.headers = {'Location': 'http://127.0.0.1/private'}
        redirect_response.is_redirect = True
        redirect_response.close = Mock()
        self.add_peer(redirect_response)
        mock_get.return_value = redirect_response

        request = self.factory.get(f'/asset-proxy?{urlencode({"url": target_url})}')
        response = asset_proxy(request)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(mock_get.call_count, 1)

    @patch('apps.tracker.views.socket.getaddrinfo', return_value=PUBLIC_ADDRINFO)
    @patch('apps.tracker.views.requests.get')
    def test_asset_proxy_blocks_internal_peer_after_public_dns_lookup(self, mock_get, mock_getaddrinfo):
        target_url = 'https://openproject.hymetry.com/assets/app.css'
        mock_get.return_value = self.upstream_response('body')
        self.add_peer(mock_get.return_value, peer_ip='127.0.0.1')

        request = self.factory.get(f'/asset-proxy?{urlencode({"url": target_url})}')
        response = asset_proxy(request)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(mock_get.call_count, 1)

    @patch('apps.tracker.views.socket.getaddrinfo', return_value=PUBLIC_ADDRINFO)
    @patch('apps.tracker.views.requests.get')
    def test_asset_proxy_blocks_html_responses(self, mock_get, mock_getaddrinfo):
        target_url = 'https://openproject.hymetry.com/assets/app.css'
        mock_get.return_value = self.upstream_response('<script>alert(1)</script>', content_type='text/html')

        request = self.factory.get(f'/asset-proxy?{urlencode({"url": target_url})}')
        response = asset_proxy(request)

        self.assertEqual(response.status_code, 415)

    @patch('apps.tracker.views.socket.getaddrinfo', return_value=PUBLIC_ADDRINFO)
    @patch('apps.tracker.views.requests.get')
    def test_asset_proxy_blocks_svg_responses(self, mock_get, mock_getaddrinfo):
        target_url = 'https://openproject.hymetry.com/logo.svg'
        mock_get.return_value = self.upstream_response('<svg></svg>', content_type='image/svg+xml')

        request = self.factory.get(f'/asset-proxy?{urlencode({"url": target_url})}')
        response = asset_proxy(request)

        self.assertEqual(response.status_code, 415)

    @override_settings(ASSET_PROXY_MAX_BYTES=4)
    @patch('apps.tracker.views.socket.getaddrinfo', return_value=PUBLIC_ADDRINFO)
    @patch('apps.tracker.views.requests.get')
    def test_asset_proxy_rejects_oversized_responses(self, mock_get, mock_getaddrinfo):
        target_url = 'https://openproject.hymetry.com/assets/app.css'
        mock_get.return_value = self.upstream_response('too-large')

        request = self.factory.get(f'/asset-proxy?{urlencode({"url": target_url})}')
        response = asset_proxy(request)

        self.assertEqual(response.status_code, 502)
