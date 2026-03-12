import logging
import os
import threading


logger = logging.getLogger(__name__)


class RuntimeURLService:
    """Resolve URLs from env, else request-derived SITE_URL."""

    def __init__(self):
        self.default_site_url = "http://localhost"
        self._runtime_site_url = ""
        self._warned = False
        self._lock = threading.Lock()

    def _clean(self, value):
        return (value or "").strip().rstrip("/")

    def _prefer_https(self, url):
        """
        Auto-upgrade Heroku public URLs to HTTPS.
        """
        if url.startswith("http://") and ".herokuapp.com" in url:
            return "https://" + url[len("http://"):]
        return url

    def _env(self, key):
        return self._prefer_https(self._clean(os.environ.get(key, "")))

    def _warn_once(self, message):
        if self._warned:
            return
        self._warned = True
        logger.warning(message)

    def ensure_initialized(self, request=None):
        """Capture SITE_URL from request if env SITE_URL is absent."""
        if self._env("SITE_URL"):
            return
        if request is None:
            return
        site = self._prefer_https(self._clean(request.build_absolute_uri("/")))
        if not site:
            return
        with self._lock:
            if not self._runtime_site_url:
                self._runtime_site_url = site

    def get_site_url(self):
        """Get SITE_URL from env, or request-captured runtime value."""
        site = self._env("SITE_URL")
        if site:
            return site
        with self._lock:
            if self._runtime_site_url:
                return self._runtime_site_url
        self._warn_once("SITE_URL is not set; using localhost fallback.")
        return self.default_site_url

    def get_app_url(self):
        """Get APP_URL from env, otherwise fallback to SITE_URL."""
        return self._env("APP_URL") or self.get_site_url()

    def get_edge_url(self):
        """Get EDGE_URL from env, otherwise fallback to SITE_URL/static/js."""
        return self._env("EDGE_URL") or f"{self.get_site_url()}/static/js"


runtime_urls = RuntimeURLService()
