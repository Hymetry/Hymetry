import logging
import os
import threading


logger = logging.getLogger(__name__)


class RuntimeURLService:
    """Resolve URLs from env, else request-derived HYMETRY_DOMAIN."""

    def __init__(self):
        self.default_domain_url = "http://localhost"
        self._runtime_domain_url = ""
        self._warned = False
        self._lock = threading.Lock()

    def _clean(self, value):
        return (value or "").strip().rstrip("/")

    def _prefer_https(self, url):
        """
        Auto-upgrade known PaaS public URLs to HTTPS.
        """
        if url.startswith("http://") and ".onrender.com" in url:
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
        """Capture runtime domain from request if env domain is absent."""
        if self._env("HYMETRY_DOMAIN"):
            return
        if request is None:
            return
        domain = self._prefer_https(self._clean(request.build_absolute_uri("/")))
        if not domain:
            return
        with self._lock:
            if not self._runtime_domain_url:
                self._runtime_domain_url = domain

    def get_hymetry_domain(self):
        """Get HYMETRY_DOMAIN from env, or request-captured runtime value."""
        domain = self._env("HYMETRY_DOMAIN")
        if domain:
            return domain
        with self._lock:
            if self._runtime_domain_url:
                return self._runtime_domain_url
        self._warn_once("HYMETRY_DOMAIN is not set; using localhost fallback.")
        return self.default_domain_url

    def get_edge_url(self):
        """Get EDGE_URL from env, otherwise fallback to HYMETRY_DOMAIN/static/js."""
        return self._env("EDGE_URL") or f"{self.get_hymetry_domain()}/static/js"


runtime_urls = RuntimeURLService()
