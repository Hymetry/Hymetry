VISITS_PRODUCT_AREA_COLOR_PALETTE = (
    '#4269D0',
    '#EFB118',
    '#FF725C',
    '#6CC5B0',
    '#3CA951',
    '#FF8AB7',
    '#A463F2',
    '#97BBF5',
    '#9C6B4E',
    '#E5E7EB',
)

KNOWN_PRODUCT_AREA_COLORS = {
    'core product': '#4269D0',
    'billing': '#EFB118',
    'developer': '#3CA951',
    'development': '#3CA951',
    'administration': '#6CC5B0',
    'admin': '#6CC5B0',
    'analytics': '#A463F2',
    'reporting': '#A463F2',
    'reports': '#A463F2',
    'collaboration': '#97BBF5',
    'integrations': '#97BBF5',
    'export': '#FF8AB7',
    'team permissions': '#9C6B4E',
    'permissions': '#9C6B4E',
    'settings': '#E5E7EB',
}


def _clean(value):
    return str(value or '').strip()


def _lookup_key(value):
    return ' '.join(_clean(value).lower().split())


def _area_value(area, keys):
    if isinstance(area, dict):
        for key in keys:
            value = _clean(area.get(key))
            if value:
                return value
    return ''


def product_area_name(area):
    if isinstance(area, dict):
        value = _area_value(
            area,
            (
                'name',
                'productArea',
                'productAreaName',
                'product_area_name',
                'product_area',
                'label',
            ),
        )
        if value:
            return value
    return _clean(area) or 'Unassigned'


def explicit_product_area_color(area):
    return _area_value(
        area,
        (
            'color',
            'productAreaColor',
            'product_area_color',
            'areaColor',
        ),
    )


def resolve_product_area_color(area, index=0, *, prefer_explicit=False):
    explicit_color = explicit_product_area_color(area)
    if prefer_explicit and explicit_color:
        return explicit_color

    known_color = KNOWN_PRODUCT_AREA_COLORS.get(_lookup_key(product_area_name(area)))
    if known_color:
        return known_color

    palette_index = index % len(VISITS_PRODUCT_AREA_COLOR_PALETTE)
    return VISITS_PRODUCT_AREA_COLOR_PALETTE[palette_index]


def resolve_product_area_colors(areas, *, prefer_explicit=False):
    resolved = []
    for index, area in enumerate(areas or []):
        item = dict(area)
        item['color'] = resolve_product_area_color(item, index, prefer_explicit=prefer_explicit)
        resolved.append(item)
    return resolved


def product_area_lookup_keys(area):
    values = []
    if isinstance(area, dict):
        for key in (
            'id',
            'key',
            'slug',
            'productAreaKey',
            'product_area_key',
            'name',
            'productArea',
            'productAreaName',
            'product_area_name',
            'product_area',
        ):
            value = _clean(area.get(key))
            if value:
                values.append(value)
    else:
        values.append(area)

    values.append(product_area_name(area))

    keys = []
    seen = set()
    for value in values:
        key = _lookup_key(value)
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def build_product_area_color_lookup(areas, *, prefer_explicit=False):
    lookup = {}
    for area in resolve_product_area_colors(areas, prefer_explicit=prefer_explicit):
        color = area.get('color') or ''
        if not color:
            continue
        for key in product_area_lookup_keys(area):
            lookup.setdefault(key, color)
    return lookup


def product_area_color_from_lookup(color_lookup, area, index=0, *, prefer_explicit=False):
    explicit_color = explicit_product_area_color(area)
    if prefer_explicit and explicit_color:
        return explicit_color

    for key in product_area_lookup_keys(area):
        color = (color_lookup or {}).get(key)
        if color:
            return color

    return resolve_product_area_color(area, index, prefer_explicit=prefer_explicit)


def apply_product_area_metadata_colors(metadata, color_lookup=None, *, prefer_explicit=False):
    lookup = color_lookup or build_product_area_color_lookup(
        (metadata or {}).values(),
        prefer_explicit=prefer_explicit,
    )
    resolved = {}
    for index, (key, area) in enumerate((metadata or {}).items()):
        item = dict(area)
        item['color'] = product_area_color_from_lookup(
            lookup,
            item,
            index,
            prefer_explicit=prefer_explicit,
        )
        resolved[key] = item
    return resolved
