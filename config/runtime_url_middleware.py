from config.runtime_url_values import runtime_urls


class RuntimeURLBootstrapMiddleware:
    """
    Bootstrap DeploymentConfig URL values once when DB config is empty.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        runtime_urls.ensure_initialized(request=request)
        return self.get_response(request)

