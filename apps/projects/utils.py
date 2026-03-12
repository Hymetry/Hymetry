from config.runtime_url_values import runtime_urls


def generate_tracking_script(api_key, custom_data):
    edge_url = runtime_urls.get_edge_url()
    minified = f'<script async src="{edge_url}/main.js" data-api-key="YOUR_CLIENTS_API_KEY"></script>'
    minified = minified.replace('YOUR_CLIENTS_API_KEY', api_key)

    return minified
