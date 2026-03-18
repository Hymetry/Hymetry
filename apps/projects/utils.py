from config.runtime_url_values import runtime_urls


def generate_tracking_script(api_key, custom_data):
    hymetry_domain = runtime_urls.get_hymetry_domain()
    edge_url = runtime_urls.get_edge_url()
    minified = (
        f'<script async src="{edge_url}/main.js" '
        f'data-api-key="YOUR_CLIENTS_API_KEY" data-api-url="{hymetry_domain}"></script>'
    )
    minified = minified.replace('YOUR_CLIENTS_API_KEY', api_key)

    return minified
