from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F

from .company_segment_reviews import mark_segments_for_deleted_attributes
from .models import (
    COMPANY_ATTRIBUTE_OPTION_COLOR_PALETTE,
    CompanyAttribute,
    CompanyAttributeBooleanDisplay,
    CompanyAttributeMoneyCurrency,
    CompanyAttributeMoneyDisplay,
    CompanyAttributeNumberFormat,
    CompanyAttributeOption,
    CompanyAttributeOptionColor,
    CompanyAttributeType,
    CompanyAttributeValue,
    Project,
)


class CompanyAttributeValidationError(Exception):
    """A complete, JSON-safe set of validation errors for one save request."""

    def __init__(self, errors):
        self.errors = errors or {'_payload': {'payload': ['The request could not be validated.']}}
        super().__init__('Company attribute validation failed.')


_TYPE_ALIASES = {
    'single-select': CompanyAttributeType.SINGLE_SELECT,
    'single_select': CompanyAttributeType.SINGLE_SELECT,
}
_COLOR_TOKENS = tuple(str(color) for color in CompanyAttributeOptionColor.values)
_COLOR_BY_TRIPLET = {
    tuple(preset[field].upper() for field in ('text', 'bg', 'border')): str(token)
    for token, preset in COMPANY_ATTRIBUTE_OPTION_COLOR_PALETTE.items()
}
_CURRENCY_SYMBOLS = {
    CompanyAttributeMoneyCurrency.USD: '$',
    CompanyAttributeMoneyCurrency.EUR: '€',
    CompanyAttributeMoneyCurrency.GBP: '£',
}


def _delete_company_attribute_filter_cache_variants(project_id):
    """Drop derived cohorts after definitions or values change.

    The unfiltered ``default`` variants do not depend on company attributes and
    remain valid. Filtered overview variants are cheap, reconstructable caches;
    deleting them prevents a previously shared URL from serving stale cohorts.
    """

    from apps.pages import services as pages_services
    from apps.pages.models import (
        CompaniesOverviewCache,
        PagesOverviewCache,
        PagesScatterTooltipCache,
        UsersOverviewCache,
    )

    for cache_model in (
        PagesOverviewCache,
        PagesScatterTooltipCache,
        CompaniesOverviewCache,
        UsersOverviewCache,
    ):
        (
            cache_model.objects
            .filter(project_id=project_id)
            .exclude(filters_hash=pages_services.DEFAULT_FILTERS_HASH)
            .delete()
        )


def _schedule_company_attribute_filter_cache_invalidation(project_id):
    from apps.projects.demo import clear_demo_project_cache_for_project

    transaction.on_commit(
        lambda: _delete_company_attribute_filter_cache_variants(project_id),
    )
    transaction.on_commit(
        lambda: clear_demo_project_cache_for_project(project_id),
    )


def bump_company_attribute_filter_revision(project_id):
    """Invalidate derived attribute cohorts inside the caller's transaction."""

    updated = Project.objects.filter(pk=project_id).update(
        filtered_analytics_revision=F('filtered_analytics_revision') + 1,
    )
    if not updated:
        raise CompanyAttributeValidationError(
            {'_payload': {'project': ['Project was not found.']}},
        )


def invalidate_company_attribute_filter_caches(project_id):
    bump_company_attribute_filter_revision(project_id)
    _schedule_company_attribute_filter_cache_invalidation(project_id)


def _add_error(errors, key, field, message):
    errors.setdefault(str(key), {}).setdefault(field, []).append(message)


def _payload_error(errors, field, message):
    _add_error(errors, '_payload', field, message)


def _object_key(raw, index, prefix='new'):
    if isinstance(raw, dict):
        client_id = raw.get('client_id')
        if client_id not in (None, ''):
            return str(client_id)
        object_id = raw.get('id')
        if object_id not in (None, ''):
            return str(object_id)
    return f'{prefix}-{index}'


def _positive_id(raw):
    if isinstance(raw, bool):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if value > 0 and str(raw).strip().lstrip('+').isdigit() else None


def _normalize_type(raw):
    value = str(raw or '').strip().lower()
    return str(_TYPE_ALIASES.get(value, value))


def _attribute_settings(attribute):
    if attribute.attribute_type == CompanyAttributeType.NUMBER:
        return {
            'format': attribute.number_format,
            'decimal_places': attribute.decimal_places,
        }
    if attribute.attribute_type == CompanyAttributeType.MONEY:
        return {
            'currency': attribute.currency,
            'display_format': attribute.money_display,
        }
    if attribute.attribute_type == CompanyAttributeType.BOOLEAN:
        return {'display_style': attribute.boolean_display}
    return {}


def _serialize_color(color_token):
    preset = COMPANY_ATTRIBUTE_OPTION_COLOR_PALETTE.get(color_token)
    if preset is None:
        preset = COMPANY_ATTRIBUTE_OPTION_COLOR_PALETTE[CompanyAttributeOptionColor.CYAN]
    return dict(preset)


def _serialize_option(option):
    return {
        'id': option.id,
        'client_id': None,
        'label': option.label,
        'position': option.position,
        'color': _serialize_color(option.color),
    }


def _serialize_attribute(attribute):
    prefetched_options = getattr(attribute, '_prefetched_objects_cache', {}).get('options')
    options = prefetched_options if prefetched_options is not None else attribute.options.all()
    return {
        'id': attribute.id,
        'client_id': None,
        'name': attribute.name,
        'type': attribute.attribute_type,
        'position': attribute.position,
        'settings': _attribute_settings(attribute),
        'options': [_serialize_option(option) for option in options],
    }


def serialize_attributes(project):
    """Return the editor's stable, JSON-safe attribute representation."""

    attributes = (
        CompanyAttribute.objects
        .filter(project=project)
        .prefetch_related('options')
        .order_by('position', 'id')
    )
    return [_serialize_attribute(attribute) for attribute in attributes]


def _normalize_color(raw, *, fallback, errors, key, field):
    if raw in (None, ''):
        return fallback

    if isinstance(raw, str):
        token = raw.strip().lower()
        if token in _COLOR_TOKENS:
            return token
    elif isinstance(raw, dict):
        token = str(raw.get('token') or raw.get('name') or '').strip().lower()
        if token in _COLOR_TOKENS:
            return token
        try:
            triplet = tuple(str(raw[field]).strip().upper() for field in ('text', 'bg', 'border'))
        except KeyError:
            triplet = ()
        if triplet in _COLOR_BY_TRIPLET:
            return _COLOR_BY_TRIPLET[triplet]

    _add_error(errors, key, field, 'Select one of the available option colors.')
    return fallback


def _normalize_options(raw_options, *, attribute_data, current_options, errors):
    key = attribute_data['key']
    if not isinstance(raw_options, list):
        _add_error(errors, key, 'options', 'Options must be a list.')
        return []

    normalized = []
    seen_ids = set()
    seen_client_ids = set()
    labels = {}
    for index, raw_option in enumerate(raw_options):
        field_prefix = f'options.{index}'
        if not isinstance(raw_option, dict):
            _add_error(errors, key, field_prefix, 'Each option must be an object.')
            continue

        raw_id = raw_option.get('id')
        option_id = None
        option_model = None
        if raw_id not in (None, ''):
            option_id = _positive_id(raw_id)
            if option_id is None:
                _add_error(errors, key, f'{field_prefix}.id', 'Enter a valid option ID.')
            elif option_id in seen_ids:
                _add_error(errors, key, f'{field_prefix}.id', 'This option appears more than once.')
            elif option_id not in current_options:
                _add_error(errors, key, f'{field_prefix}.id', 'This option does not belong to the attribute.')
            else:
                option_model = current_options[option_id]
            if option_id is not None:
                seen_ids.add(option_id)

        client_id = raw_option.get('client_id')
        if client_id not in (None, ''):
            client_id = str(client_id)
            if client_id in seen_client_ids:
                _add_error(errors, key, f'{field_prefix}.client_id', 'This client ID appears more than once.')
            seen_client_ids.add(client_id)
        else:
            client_id = None

        label = raw_option.get('label')
        label = label.strip() if isinstance(label, str) else ''
        if not label:
            _add_error(errors, key, f'{field_prefix}.label', 'Enter an option label.')
        elif len(label) > 100:
            _add_error(errors, key, f'{field_prefix}.label', 'Option labels cannot exceed 100 characters.')
        folded_label = label.casefold()
        if folded_label and folded_label in labels:
            _add_error(errors, key, f'{field_prefix}.label', 'Option labels must be unique within the attribute.')
        elif folded_label:
            labels[folded_label] = index

        fallback = option_model.color if option_model else _COLOR_TOKENS[(index + 8) % len(_COLOR_TOKENS)]
        color_raw = raw_option.get('color')
        if color_raw is None and any(color_field in raw_option for color_field in ('color_text', 'color_bg', 'color_border')):
            color_raw = {
                'text': raw_option.get('color_text'),
                'bg': raw_option.get('color_bg'),
                'border': raw_option.get('color_border'),
            }
        color = _normalize_color(
            color_raw,
            fallback=fallback,
            errors=errors,
            key=key,
            field=f'{field_prefix}.color',
        )
        normalized.append({
            'model': option_model,
            'id': option_id,
            'client_id': client_id,
            'label': label,
            'color': color,
            'position': index,
        })

    if not normalized:
        _add_error(errors, key, 'options', 'Add at least one option.')
    return normalized


def _normalize_attribute(raw, *, index, current_attributes, errors):
    key = _object_key(raw, index)
    if not isinstance(raw, dict):
        _add_error(errors, key, 'attribute', 'Each attribute must be an object.')
        return None

    raw_id = raw.get('id')
    attribute_id = None
    attribute = None
    if raw_id not in (None, ''):
        attribute_id = _positive_id(raw_id)
        if attribute_id is None:
            _add_error(errors, key, 'id', 'Enter a valid attribute ID.')
        elif attribute_id not in current_attributes:
            _add_error(errors, key, 'id', 'This attribute does not belong to the project.')
        else:
            attribute = current_attributes[attribute_id]

    client_id = raw.get('client_id')
    client_id = str(client_id) if client_id not in (None, '') else None
    name = raw.get('name')
    name = name.strip() if isinstance(name, str) else ''
    if not name:
        _add_error(errors, key, 'name', 'Enter an attribute name.')
    elif len(name) > 100:
        _add_error(errors, key, 'name', 'Attribute names cannot exceed 100 characters.')

    raw_type = raw.get('type', raw.get('attribute_type'))
    attribute_type = _normalize_type(raw_type if raw_type not in (None, '') else getattr(attribute, 'attribute_type', ''))
    if attribute_type not in CompanyAttributeType.values:
        _add_error(errors, key, 'type', 'Select a valid attribute type.')
    if attribute and attribute_type != attribute.attribute_type:
        _add_error(errors, key, 'type', 'Attribute type cannot be changed after creation.')

    settings = raw.get('settings', {})
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        _add_error(errors, key, 'settings', 'Settings must be an object.')
        settings = {}

    normalized = {
        'model': attribute,
        'id': attribute_id,
        'key': key,
        'client_id': client_id,
        'name': name,
        'type': attribute_type,
        'position': index,
        'number_format': '',
        'decimal_places': None,
        'currency': '',
        'money_display': '',
        'boolean_display': '',
        'options': None,
        'options_supplied': 'options' in raw,
    }

    if attribute_type == CompanyAttributeType.NUMBER:
        number_format = settings.get(
            'format',
            raw.get('number_format', getattr(attribute, 'number_format', CompanyAttributeNumberFormat.PLAIN)),
        )
        number_format = str(number_format or '').strip().lower()
        if number_format not in CompanyAttributeNumberFormat.values:
            _add_error(errors, key, 'settings.format', 'Select plain or percentage format.')
        normalized['number_format'] = number_format

        decimal_places = settings.get(
            'decimal_places',
            raw.get('decimal_places', getattr(attribute, 'decimal_places', 0)),
        )
        if isinstance(decimal_places, int) and not isinstance(decimal_places, bool):
            parsed_decimal_places = decimal_places
        elif isinstance(decimal_places, str) and decimal_places.strip() in {'0', '1', '2'}:
            parsed_decimal_places = int(decimal_places.strip())
        else:
            parsed_decimal_places = None
        if parsed_decimal_places not in (0, 1, 2):
            _add_error(errors, key, 'settings.decimal_places', 'Decimal places must be 0, 1, or 2.')
        normalized['decimal_places'] = parsed_decimal_places

    elif attribute_type == CompanyAttributeType.MONEY:
        currency = settings.get('currency', raw.get('currency', getattr(attribute, 'currency', 'USD')))
        currency = str(currency or '').strip().upper()
        if currency not in CompanyAttributeMoneyCurrency.values:
            _add_error(errors, key, 'settings.currency', 'Select a valid currency.')
        normalized['currency'] = currency

        display_format = settings.get(
            'display_format',
            raw.get('money_display', getattr(attribute, 'money_display', CompanyAttributeMoneyDisplay.COMPACT)),
        )
        display_format = str(display_format or '').strip().lower()
        if display_format not in CompanyAttributeMoneyDisplay.values:
            _add_error(errors, key, 'settings.display_format', 'Select compact or full display format.')
        normalized['money_display'] = display_format

    elif attribute_type == CompanyAttributeType.BOOLEAN:
        display_style = settings.get(
            'display_style',
            raw.get('boolean_display', getattr(attribute, 'boolean_display', CompanyAttributeBooleanDisplay.YES_NO)),
        )
        display_style = str(display_style or '').strip().lower()
        if display_style not in CompanyAttributeBooleanDisplay.values:
            _add_error(errors, key, 'settings.display_style', 'Select a valid boolean display style.')
        normalized['boolean_display'] = display_style

    current_options = {option.id: option for option in attribute.options.all()} if attribute else {}
    if attribute_type == CompanyAttributeType.SINGLE_SELECT:
        if 'options' in raw:
            normalized['options'] = _normalize_options(
                raw.get('options'),
                attribute_data=normalized,
                current_options=current_options,
                errors=errors,
            )
        elif attribute:
            normalized['options'] = [
                {
                    'model': option,
                    'id': option.id,
                    'client_id': None,
                    'label': option.label,
                    'color': option.color,
                    'position': option.position,
                }
                for option in attribute.options.all()
            ]
        else:
            normalized['options'] = []
            _add_error(errors, key, 'options', 'Add at least one option.')
    elif raw.get('options'):
        _add_error(errors, key, 'options', 'Options are only valid for single-select attributes.')

    return normalized


def _normalize_deleted_ids(payload, current_attributes, errors):
    raw_deleted = payload.get('deleted_ids', payload.get('deleted_attribute_ids', []))
    if raw_deleted is None:
        raw_deleted = []
    if not isinstance(raw_deleted, list):
        _payload_error(errors, 'deleted_ids', 'Deleted IDs must be a list.')
        return set()

    deleted_ids = set()
    for index, raw_id in enumerate(raw_deleted):
        attribute_id = _positive_id(raw_id)
        if attribute_id is None:
            _payload_error(errors, f'deleted_ids.{index}', 'Enter a valid attribute ID.')
        elif attribute_id not in current_attributes:
            _payload_error(errors, f'deleted_ids.{index}', 'This attribute does not belong to the project.')
        elif attribute_id in deleted_ids:
            _payload_error(errors, f'deleted_ids.{index}', 'This attribute is listed more than once.')
        else:
            deleted_ids.add(attribute_id)
    return deleted_ids


def _validate_final_names(normalized, current_attributes, deleted_ids, listed_ids, errors):
    final_names = {}
    for data in normalized:
        if data is None or not data['name']:
            continue
        folded = data['name'].casefold()
        if folded in final_names:
            _add_error(errors, data['key'], 'name', 'Attribute names must be unique within the project.')
            _add_error(errors, final_names[folded], 'name', 'Attribute names must be unique within the project.')
        else:
            final_names[folded] = data['key']

    for attribute_id, attribute in current_attributes.items():
        if attribute_id in deleted_ids or attribute_id in listed_ids:
            continue
        folded = attribute.name.casefold()
        if folded in final_names:
            _add_error(errors, final_names[folded], 'name', 'Attribute names must be unique within the project.')
        else:
            final_names[folded] = str(attribute_id)


def _set_attribute_fields(attribute, data, position):
    attribute.name = data['name']
    attribute.attribute_type = data['type']
    attribute.position = position
    attribute.number_format = data['number_format']
    attribute.decimal_places = data['decimal_places']
    attribute.currency = data['currency']
    attribute.money_display = data['money_display']
    attribute.boolean_display = data['boolean_display']


def _save_options(attribute, data):
    if data['type'] != CompanyAttributeType.SINGLE_SELECT:
        attribute.options.all().delete()
        return

    option_data = data['options'] or []
    retained_ids = {item['id'] for item in option_data if item['id'] is not None}
    removed_ids = set(attribute.options.values_list('id', flat=True)) - retained_ids
    if removed_ids:
        CompanyAttributeValue.objects.filter(option_id__in=removed_ids).delete()
        CompanyAttributeOption.objects.filter(id__in=removed_ids).delete()

    temporary_prefix = f'__pending_{uuid4().hex}_'
    for item in option_data:
        if item['model'] is not None:
            CompanyAttributeOption.objects.filter(pk=item['model'].pk).update(
                label=f'{temporary_prefix}{item["model"].pk}'[:100],
            )

    for position, item in enumerate(option_data):
        option = item['model'] or CompanyAttributeOption(attribute=attribute)
        option.attribute = attribute
        option.label = item['label']
        option.color = item['color']
        option.position = position
        option.save()


@transaction.atomic
def save_attribute_definitions(project, payload, *, actor=None):
    """Validate and atomically apply an attribute-manager draft.

    ``attributes`` is the current ordered editor list. Existing attributes omitted
    from it are left in place; only ``deleted_ids`` causes deletion.

    A deletion reaches beyond the attribute itself: *actor* is recorded on every
    company segment in the project that still references the attribute, whoever
    owns it, so the owner can be told what happened before the segment is used
    again.
    """

    if not isinstance(payload, dict):
        raise CompanyAttributeValidationError({'_payload': {'payload': ['The payload must be an object.']}})
    if not getattr(project, 'pk', None):
        raise CompanyAttributeValidationError({'_payload': {'project': ['Save the project first.']}})

    # Locking the project serializes definition and value writes for this project.
    try:
        Project.objects.select_for_update().get(pk=project.pk)
    except Project.DoesNotExist as exc:
        raise CompanyAttributeValidationError({'_payload': {'project': ['Project was not found.']}}) from exc

    current_list = list(
        CompanyAttribute.objects
        .select_for_update()
        .filter(project_id=project.pk)
        .prefetch_related('options')
        .order_by('position', 'id')
    )
    current_attributes = {attribute.id: attribute for attribute in current_list}
    errors = {}
    deleted_ids = _normalize_deleted_ids(payload, current_attributes, errors)

    raw_attributes = payload.get('attributes', [])
    if not isinstance(raw_attributes, list):
        _payload_error(errors, 'attributes', 'Attributes must be a list.')
        raw_attributes = []

    normalized = []
    listed_ids = set()
    listed_client_ids = set()
    for index, raw in enumerate(raw_attributes):
        data = _normalize_attribute(raw, index=index, current_attributes=current_attributes, errors=errors)
        if data is None:
            continue
        if data['id'] is not None:
            if data['id'] in listed_ids:
                _add_error(errors, data['key'], 'id', 'This attribute appears more than once.')
            listed_ids.add(data['id'])
            if data['id'] in deleted_ids:
                _add_error(errors, data['key'], 'id', 'A deleted attribute cannot also be saved.')
        if data['client_id'] is not None:
            if data['client_id'] in listed_client_ids:
                _add_error(errors, data['key'], 'client_id', 'This client ID appears more than once.')
            listed_client_ids.add(data['client_id'])
        normalized.append(data)

    _validate_final_names(normalized, current_attributes, deleted_ids, listed_ids, errors)
    if errors:
        raise CompanyAttributeValidationError(errors)

    try:
        if deleted_ids:
            # Segments are flagged first: once the rows are gone their names are
            # unrecoverable, and the flag is what stops a half-empty definition
            # from being applied as if nothing had changed.
            mark_segments_for_deleted_attributes(
                project.pk,
                [current_attributes[attribute_id] for attribute_id in sorted(deleted_ids)],
                actor,
            )
            CompanyAttribute.objects.filter(project_id=project.pk, id__in=deleted_ids).delete()

        temporary_prefix = f'__pending_{uuid4().hex}_'
        for data in normalized:
            if data['model'] is not None:
                CompanyAttribute.objects.filter(pk=data['model'].pk).update(
                    name=f'{temporary_prefix}{data["model"].pk}'[:100],
                )

        for position, data in enumerate(normalized):
            attribute = data['model'] or CompanyAttribute(project_id=project.pk)
            _set_attribute_fields(attribute, data, position)
            attribute.save()
            _save_options(attribute, data)

        # Omitted attributes are preserved after the explicit editor order.
        omitted = [
            attribute
            for attribute in current_list
            if attribute.id not in deleted_ids and attribute.id not in listed_ids
        ]
        for offset, attribute in enumerate(omitted, start=len(normalized)):
            if attribute.position != offset:
                CompanyAttribute.objects.filter(pk=attribute.pk).update(position=offset)
    except (IntegrityError, ValidationError) as exc:
        raise CompanyAttributeValidationError({
            '_payload': {'save': ['The attributes could not be saved because they conflict with current data.']},
        }) from exc

    invalidate_company_attribute_filter_caches(project.pk)
    return serialize_attributes(project)


def _is_blank(raw):
    return raw is None or (isinstance(raw, str) and not raw.strip())


def _parse_decimal(raw):
    if isinstance(raw, bool):
        raise ValueError
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError from None
    if not value.is_finite():
        raise ValueError
    field = CompanyAttributeValue._meta.get_field('decimal_value')
    try:
        return field.clean(value, None)
    except ValidationError as exc:
        raise ValueError from exc


def _parse_date(raw):
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if not isinstance(raw, str):
        raise ValueError
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        raise ValueError from None


def _parse_boolean(raw):
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int) and raw in (0, 1):
        return bool(raw)
    value = str(raw or '').strip().lower()
    if value in {'true', '1', 'yes'}:
        return True
    if value in {'false', '0', 'no'}:
        return False
    raise ValueError


def _normalize_value_items(payload, errors):
    if isinstance(payload, dict) and 'values' in payload:
        payload = payload['values']

    if isinstance(payload, dict):
        return [{'attribute_id': key, 'value': value} for key, value in payload.items()]
    if isinstance(payload, list):
        return payload
    _payload_error(errors, 'values', 'Values must be an object or a list.')
    return []


def _normalized_value_defaults(attribute, raw, errors, key):
    defaults = {
        'text_value': None,
        'decimal_value': None,
        'date_value': None,
        'boolean_value': None,
        'option': None,
    }
    try:
        if attribute.attribute_type == CompanyAttributeType.TEXT:
            if not isinstance(raw, str):
                raise ValueError
            defaults['text_value'] = raw
        elif attribute.attribute_type in (CompanyAttributeType.NUMBER, CompanyAttributeType.MONEY):
            defaults['decimal_value'] = _parse_decimal(raw)
        elif attribute.attribute_type == CompanyAttributeType.DATE:
            defaults['date_value'] = _parse_date(raw)
        elif attribute.attribute_type == CompanyAttributeType.BOOLEAN:
            defaults['boolean_value'] = _parse_boolean(raw)
        elif attribute.attribute_type == CompanyAttributeType.SINGLE_SELECT:
            option_raw = raw.get('id') if isinstance(raw, dict) else raw
            option_id = _positive_id(option_raw)
            option = attribute.options.filter(pk=option_id).first() if option_id is not None else None
            if option is None:
                raise ValueError
            defaults['option'] = option
        else:
            raise ValueError
    except ValueError:
        message = {
            CompanyAttributeType.TEXT: 'Enter text.',
            CompanyAttributeType.NUMBER: 'Enter a valid number.',
            CompanyAttributeType.MONEY: 'Enter a valid amount.',
            CompanyAttributeType.DATE: 'Enter a valid date in YYYY-MM-DD format.',
            CompanyAttributeType.BOOLEAN: 'Select yes or no.',
            CompanyAttributeType.SINGLE_SELECT: 'Select a valid option.',
        }.get(attribute.attribute_type, 'Enter a valid value.')
        _add_error(errors, key, 'value', message)
        return None
    return defaults


@transaction.atomic
def save_company_attribute_values(project, company_id, payload):
    """Validate a company's typed values as one atomic save; blanks clear rows."""

    if not getattr(project, 'pk', None):
        raise CompanyAttributeValidationError({'_payload': {'project': ['Save the project first.']}})
    company_id = str(company_id or '').strip()
    errors = {}
    if not company_id:
        _payload_error(errors, 'company_id', 'Company ID is required.')
    elif len(company_id) > 255:
        _payload_error(errors, 'company_id', 'Company ID cannot exceed 255 characters.')

    try:
        Project.objects.select_for_update().get(pk=project.pk)
    except Project.DoesNotExist:
        _payload_error(errors, 'project', 'Project was not found.')

    attributes = {
        attribute.id: attribute
        for attribute in (
            CompanyAttribute.objects
            .select_for_update()
            .filter(project_id=project.pk)
            .prefetch_related('options')
        )
    }
    items = _normalize_value_items(payload, errors)
    normalized = []
    seen = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            _payload_error(errors, f'values.{index}', 'Each value must be an object.')
            continue
        raw_attribute_id = item.get('attribute_id', item.get('id'))
        attribute_id = _positive_id(raw_attribute_id)
        key = str(raw_attribute_id) if raw_attribute_id not in (None, '') else f'value-{index}'
        if attribute_id is None:
            _add_error(errors, key, 'attribute_id', 'Enter a valid attribute ID.')
            continue
        if attribute_id in seen:
            _add_error(errors, key, 'attribute_id', 'This attribute appears more than once.')
            continue
        seen.add(attribute_id)
        attribute = attributes.get(attribute_id)
        if attribute is None:
            _add_error(errors, key, 'attribute_id', 'This attribute does not belong to the project.')
            continue

        raw = item.get('value')
        if _is_blank(raw):
            normalized.append((attribute, None))
            continue
        defaults = _normalized_value_defaults(attribute, raw, errors, key)
        if defaults is not None:
            normalized.append((attribute, defaults))

    if errors:
        raise CompanyAttributeValidationError(errors)

    try:
        for attribute, defaults in normalized:
            if defaults is None:
                CompanyAttributeValue.objects.filter(attribute=attribute, company_id=company_id).delete()
            else:
                CompanyAttributeValue.objects.update_or_create(
                    attribute=attribute,
                    company_id=company_id,
                    defaults=defaults,
                )
    except (IntegrityError, ValidationError) as exc:
        raise CompanyAttributeValidationError({
            '_payload': {'save': ['The company values could not be saved because they conflict with current data.']},
        }) from exc

    invalidate_company_attribute_filter_caches(project.pk)
    return list(
        CompanyAttributeValue.objects
        .filter(attribute__project_id=project.pk, company_id=company_id)
        .select_related('attribute', 'option')
        .order_by('attribute__position', 'attribute_id')
    )


def _decimal_raw(value):
    rendered = format(value, 'f')
    if '.' in rendered:
        rendered = rendered.rstrip('0').rstrip('.')
    return rendered or '0'


def _rounded_decimal(value, decimal_places):
    quantum = Decimal(1).scaleb(-decimal_places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _compact_decimal(value):
    absolute = abs(value)
    suffix = ''
    divisor = Decimal(1)
    for threshold, candidate_suffix in (
        (Decimal('1000000000000'), 'T'),
        (Decimal('1000000000'), 'B'),
        (Decimal('1000000'), 'M'),
        (Decimal('1000'), 'K'),
    ):
        if absolute >= threshold:
            suffix = candidate_suffix
            divisor = threshold
            break
    scaled = value / divisor
    places = 0 if scaled == scaled.to_integral_value() else 1
    return f'{_rounded_decimal(scaled, places):.{places}f}{suffix}'


def display_company_attribute_value(attribute, value):
    if value is None:
        return '-'
    if attribute.attribute_type == CompanyAttributeType.TEXT:
        return value.text_value
    if attribute.attribute_type == CompanyAttributeType.NUMBER:
        places = attribute.decimal_places or 0
        rendered = f'{_rounded_decimal(value.decimal_value, places):,.{places}f}'
        return f'{rendered}%' if attribute.number_format == CompanyAttributeNumberFormat.PERCENTAGE else rendered
    if attribute.attribute_type == CompanyAttributeType.MONEY:
        symbol = _CURRENCY_SYMBOLS.get(attribute.currency, f'{attribute.currency} ')
        if attribute.money_display == CompanyAttributeMoneyDisplay.COMPACT:
            return f'{symbol}{_compact_decimal(value.decimal_value)}'
        rendered = f'{value.decimal_value:,.10f}'.rstrip('0').rstrip('.')
        return f'{symbol}{rendered}'
    if attribute.attribute_type == CompanyAttributeType.DATE:
        return f'{value.date_value:%b} {value.date_value.day}, {value.date_value.year}'
    if attribute.attribute_type == CompanyAttributeType.BOOLEAN:
        if attribute.boolean_display == CompanyAttributeBooleanDisplay.CHECKMARK_DASH:
            return '✓' if value.boolean_value else '—'
        return 'Yes' if value.boolean_value else 'No'
    if attribute.attribute_type == CompanyAttributeType.SINGLE_SELECT:
        return value.option.label if value.option_id else '-'
    return '-'


def serialize_company_attribute_value(value):
    attribute = value.attribute
    color = None
    if attribute.attribute_type == CompanyAttributeType.TEXT:
        raw = value.text_value
    elif attribute.attribute_type in (CompanyAttributeType.NUMBER, CompanyAttributeType.MONEY):
        raw = _decimal_raw(value.decimal_value)
    elif attribute.attribute_type == CompanyAttributeType.DATE:
        raw = value.date_value.isoformat()
    elif attribute.attribute_type == CompanyAttributeType.BOOLEAN:
        raw = value.boolean_value
    elif attribute.attribute_type == CompanyAttributeType.SINGLE_SELECT:
        raw = value.option_id
        if value.option_id:
            color = _serialize_color(value.option.color)
    else:
        raw = None

    result = {
        'raw': raw,
        'display': display_company_attribute_value(attribute, value),
    }
    if color is not None:
        result['color'] = color
    return result


def sort_company_attribute_value(value):
    """Return the native scalar used for typed table ordering."""

    if value is None:
        return None
    attribute_type = value.attribute.attribute_type
    if attribute_type == CompanyAttributeType.TEXT:
        return value.text_value.casefold() if value.text_value is not None else None
    if attribute_type in (CompanyAttributeType.NUMBER, CompanyAttributeType.MONEY):
        return value.decimal_value
    if attribute_type == CompanyAttributeType.DATE:
        return value.date_value
    if attribute_type == CompanyAttributeType.BOOLEAN:
        return value.boolean_value
    if attribute_type == CompanyAttributeType.SINGLE_SELECT:
        return value.option.label.casefold() if value.option_id else None
    return None
