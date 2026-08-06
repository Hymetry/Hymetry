from config.runtime_url_values import runtime_urls


TRACKING_MODE_ANALYTICS_ONLY = 'analytics'
TRACKING_MODE_ANALYTICS_AND_RECORDING = 'analytics,recording'
TRACKING_MODE_LABELS = {
    TRACKING_MODE_ANALYTICS_AND_RECORDING: 'Analytics and screen recording',
    TRACKING_MODE_ANALYTICS_ONLY: 'Analytics',
}


def normalize_capture_modes(raw_value):
    if not raw_value:
        return TRACKING_MODE_ANALYTICS_AND_RECORDING

    if isinstance(raw_value, (list, tuple, set)):
        parts = [str(item).strip().lower() for item in raw_value]
    else:
        parts = [part.strip().lower() for part in str(raw_value).split(',')]

    selected = set()
    for value in parts:
        if value in ("recording", "analytics"):
            selected.add(value)

    if not selected:
        return TRACKING_MODE_ANALYTICS_AND_RECORDING

    ordered = []
    if "analytics" in selected:
        ordered.append("analytics")
    if "recording" in selected:
        ordered.append("recording")

    return ",".join(ordered)


def normalize_tracking_mode_choice(raw_value):
    normalized_capture = normalize_capture_modes(raw_value)
    capture_values = {value for value in normalized_capture.split(',') if value}

    if 'recording' in capture_values:
        return TRACKING_MODE_ANALYTICS_AND_RECORDING
    return TRACKING_MODE_ANALYTICS_ONLY


def get_tracking_mode_label(raw_value):
    tracking_mode = normalize_tracking_mode_choice(raw_value)
    return TRACKING_MODE_LABELS[tracking_mode]


def generate_identify_settings_snippet():
    return (
        "<script>\n"
        "  window.hymetrySettings = {\n"
        "    identify: {\n"
        "      user: {\n"
        "        id: \"USER_ID\",\n"
        "        traits: {\n"
        "          name: \"Jane Cooper\",\n"
        "          email: \"jane@example.com\"\n"
        "        }\n"
        "      },\n"
        "      company: {\n"
        "        id: \"COMPANY_ID\",\n"
        "        traits: {\n"
        "          name: \"Acme Inc.\"\n"
        "        }\n"
        "      }\n"
        "    }\n"
        "  };\n"
        "</script>"
    )


TRACKING_MODE_ANALYTICS_ONLY = 'analytics'
TRACKING_MODE_ANALYTICS_AND_RECORDING = 'analytics,recording'
TRACKING_MODE_LABELS = {
    TRACKING_MODE_ANALYTICS_AND_RECORDING: 'Analytics and screen recording',
    TRACKING_MODE_ANALYTICS_ONLY: 'Analytics',
}


def normalize_capture_modes(raw_value):
    if not raw_value:
        return TRACKING_MODE_ANALYTICS_ONLY

    if isinstance(raw_value, (list, tuple, set)):
        parts = [str(item).strip().lower() for item in raw_value]
    else:
        parts = [part.strip().lower() for part in str(raw_value).split(',')]

    selected = set()
    for value in parts:
        if value in ("recording", "analytics"):
            selected.add(value)

    if not selected:
        return TRACKING_MODE_ANALYTICS_ONLY

    ordered = []
    if "analytics" in selected:
        ordered.append("analytics")
    if "recording" in selected:
        ordered.append("recording")

    return ",".join(ordered)


def normalize_tracking_mode_choice(raw_value):
    normalized_capture = normalize_capture_modes(raw_value)
    capture_values = {value for value in normalized_capture.split(',') if value}

    if 'recording' in capture_values:
        return TRACKING_MODE_ANALYTICS_AND_RECORDING
    return TRACKING_MODE_ANALYTICS_ONLY


def get_tracking_mode_label(raw_value):
    tracking_mode = normalize_tracking_mode_choice(raw_value)
    return TRACKING_MODE_LABELS[tracking_mode]


def generate_identify_settings_snippet():
    return (
        "<script>\n"
        "  window.hymetrySettings = {\n"
        "    identify: {\n"
        "      user: {\n"
        "        id: \"USER_ID\",\n"
        "        traits: {\n"
        "          name: \"Jane Cooper\",\n"
        "          email: \"jane@example.com\"\n"
        "        }\n"
        "      },\n"
        "      company: {\n"
        "        id: \"COMPANY_ID\",\n"
        "        traits: {\n"
        "          name: \"Acme Inc.\"\n"
        "        }\n"
        "      }\n"
        "    }\n"
        "  };\n"
        "</script>"
    )


def generate_tracking_script(api_key, custom_data):
    edge_url = runtime_urls.get_edge_url()
    hymetry_domain = runtime_urls.get_hymetry_domain()
    custom_data = custom_data or {}
    capture = normalize_capture_modes(custom_data.get('capture'))

    minified = (
        f'<script async src="{edge_url}/main.js" data-api-key="YOUR_CLIENTS_API_KEY" '
        f'data-api-url="{hymetry_domain}" data-capture="{capture}"></script>'
    )
    minified = minified.replace('YOUR_CLIENTS_API_KEY', api_key)

    return minified
