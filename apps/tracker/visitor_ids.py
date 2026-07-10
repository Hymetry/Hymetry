import uuid


def normalize_project_visitor_uuid(project_id, value):
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        return uuid.UUID(text)
    except (AttributeError, TypeError, ValueError):
        return uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"hymetry:project:{project_id}:visitor:{text}",
        )
