import json
import os

from django.conf import settings


def generate_tracking_script(api_key, custom_data):
    edge_url = getattr(settings, 'EDGE_URL', 'http://localhost:8001')
    minified = f'<script async src="{edge_url}/main.js" data-api-key="YOUR_CLIENTS_API_KEY"></script>'
    minified = minified.replace('YOUR_CLIENTS_API_KEY', api_key)

    return minified
