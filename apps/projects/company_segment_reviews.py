"""Company segments left dangling by a deleted company attribute.

Deleting a company attribute is a project-wide act: any member, admin, or owner
may do it, and it can invalidate a segment that belongs to somebody else. The
segment is never renamed and its stored definition is never rewritten behind the
owner's back. Instead the segment is flagged ``needs_review`` and carries the
deletion record it has to explain — attribute name, who deleted it, and when —
until its owner opens it, drops the orphaned conditions, and saves.

Everything here works from ``CompanySegment.definition`` keys, which are the
immutable numeric attribute IDs. That is what makes a reference to a deleted
attribute still detectable after the attribute row itself is gone.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from .models import CompanySegment


def _project_zone(timezone_name: Any) -> ZoneInfo:
    try:
        return ZoneInfo(str(timezone_name or 'UTC'))
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo('UTC')


def actor_display_name(user: Any) -> str:
    """The name a workspace shows for *user*, falling back to their email."""

    if user is None:
        return 'a teammate'
    full_name = ''
    getter = getattr(user, 'get_full_name', None)
    if callable(getter):
        full_name = str(getter() or '').strip()
    if full_name:
        return full_name
    email = str(getattr(user, 'email', '') or '').strip()
    if email:
        return email
    return str(getattr(user, 'username', '') or '').strip() or 'a teammate'


def _definition_attribute_ids(definition: Any) -> set[str]:
    if not isinstance(definition, Mapping):
        return set()
    return {str(key).strip() for key in definition.keys() if str(key).strip()}


def _normalized_records(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    records = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        attribute_id = str(entry.get('attribute_id') or '').strip()
        if not attribute_id:
            continue
        records.append({
            'attribute_id': attribute_id,
            'attribute_name': str(entry.get('attribute_name') or '').strip(),
            'deleted_by': str(entry.get('deleted_by') or '').strip(),
            'deleted_at': str(entry.get('deleted_at') or '').strip(),
        })
    return records


def _attribute_sort_key(attribute_id: str) -> tuple[int, int, str]:
    text = str(attribute_id)
    return (0, int(text), '') if text.isdigit() else (1, 0, text)


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or '').strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed, ZoneInfo('UTC'))


def deletion_date_label(value: Any, project_timezone: Any = 'UTC') -> str:
    """Render a deletion timestamp the way the banners read it: ``July 24``."""

    parsed = _parse_timestamp(value)
    if parsed is None:
        return ''
    local = parsed.astimezone(_project_zone(project_timezone))
    return f'{local:%B} {local.day}'


def deletion_banner_message(record: Mapping[str, Any], project_timezone: Any = 'UTC') -> str:
    """The page-banner sentence for one deleted attribute."""

    name = str(record.get('attribute_name') or '').strip() or 'A company attribute'
    actor = str(record.get('deleted_by') or '').strip()
    date_label = deletion_date_label(record.get('deleted_at'), project_timezone)
    sentence = f'The attribute "{name}" was deleted'
    if actor:
        sentence += f' by {actor}'
    if date_label:
        sentence += f' on {date_label}'
    return f'{sentence}. It was used in some of your segments.'


def deletion_detail(record: Mapping[str, Any], project_timezone: Any = 'UTC') -> str:
    """The editor line for one deleted attribute, without the banner's tail."""

    name = str(record.get('attribute_name') or '').strip() or 'A company attribute'
    actor = str(record.get('deleted_by') or '').strip()
    date_label = deletion_date_label(record.get('deleted_at'), project_timezone)
    sentence = f'"{name}" was deleted'
    if actor:
        sentence += f' by {actor}'
    if date_label:
        sentence += f' on {date_label}'
    return f'{sentence}.'


def serialize_deletion_records(
    segment: CompanySegment,
    project_timezone: Any = 'UTC',
) -> list[dict[str, str]]:
    """The deletion records a segment still owes its owner an explanation for."""

    referenced = _definition_attribute_ids(segment.definition)
    return [
        {
            'attributeId': record['attribute_id'],
            'attributeName': record['attribute_name'],
            'deletedBy': record['deleted_by'],
            'deletedOn': deletion_date_label(record['deleted_at'], project_timezone),
            'message': deletion_banner_message(record, project_timezone),
            'detail': deletion_detail(record, project_timezone),
        }
        for record in _normalized_records(segment.pending_attribute_deletions)
        if record['attribute_id'] in referenced
    ]


def segment_deleted_attribute_ids(segment: CompanySegment) -> set[str]:
    """Deleted attribute IDs the stored definition still references."""

    referenced = _definition_attribute_ids(segment.definition)
    return {
        record['attribute_id']
        for record in _normalized_records(segment.pending_attribute_deletions)
        if record['attribute_id'] in referenced
    }


def mark_segments_for_deleted_attributes(
    project_id: Any,
    attributes: Iterable[Any],
    actor: Any = None,
    *,
    deleted_at: datetime | None = None,
) -> list[CompanySegment]:
    """Flag every segment in the project that references a deleted attribute.

    Ownership is deliberately ignored: an attribute belongs to the project, so
    one member's deletion has to reach the segments of everyone else — and the
    project's ownerless seeded segments too.

    Call this *before* the attributes are deleted, while their names can still
    be read. Returns the segments that were flagged.
    """

    records_by_id = {}
    for attribute in attributes:
        attribute_id = str(getattr(attribute, 'id', '') or '').strip()
        if not attribute_id:
            continue
        records_by_id[attribute_id] = {
            'attribute_id': attribute_id,
            'attribute_name': str(getattr(attribute, 'name', '') or '').strip(),
            'deleted_by': actor_display_name(actor),
            'deleted_at': (deleted_at or timezone.now()).isoformat(),
        }
    if not records_by_id:
        return []

    flagged = []
    segments = CompanySegment.objects.select_for_update().filter(project_id=project_id)
    for segment in segments:
        referenced = _definition_attribute_ids(segment.definition) & set(records_by_id)
        if not referenced:
            continue
        # A second deletion supersedes an unreviewed record for the same
        # attribute; anything the owner has not seen yet is otherwise kept.
        pending = [
            record
            for record in _normalized_records(segment.pending_attribute_deletions)
            if record['attribute_id'] not in referenced
        ]
        pending.extend(records_by_id[attribute_id] for attribute_id in sorted(referenced))
        # Written through the queryset so ``updated_at`` keeps meaning "last
        # edited by its owner" rather than "last disturbed by someone else".
        CompanySegment.objects.filter(pk=segment.pk).update(
            needs_review=True,
            pending_attribute_deletions=pending,
        )
        segment.needs_review = True
        segment.pending_attribute_deletions = pending
        flagged.append(segment)
    return flagged


def clear_segment_review_if_resolved(segment: CompanySegment) -> bool:
    """Drop the review flag once no deleted attribute is referenced any more.

    Returns whether the segment came out of review. A rename or any other save
    that leaves an orphaned condition in place keeps the flag: the rule is about
    the definition, not about having visited the editor.
    """

    if not segment.needs_review:
        return False
    if segment_deleted_attribute_ids(segment):
        return False
    segment.needs_review = False
    segment.pending_attribute_deletions = []
    CompanySegment.objects.filter(pk=segment.pk).update(
        needs_review=False,
        pending_attribute_deletions=[],
    )
    return True


def segments_needing_review(project, user) -> list[CompanySegment]:
    """The signed-in owner's own segments still waiting for a review."""

    if not getattr(user, 'is_authenticated', False):
        return []
    return list(
        CompanySegment.objects
        .filter(project=project, user=user, needs_review=True)
        .order_by('name', 'id')
    )


def review_notice(project, user) -> dict[str, Any]:
    """Banner content for the owner of segments that need review.

    Deleted attributes are deduplicated across the owner's segments, so one
    deletion produces one sentence however many segments it touched.
    """

    project_timezone = getattr(project, 'timezone', 'UTC')
    messages: dict[str, dict[str, str]] = {}
    segment_count = 0
    for segment in segments_needing_review(project, user):
        records = serialize_deletion_records(segment, project_timezone)
        if not records:
            continue
        segment_count += 1
        for record in records:
            messages.setdefault(record['attributeId'], record)
    if not messages:
        return {'active': False, 'attributes': [], 'messages': [], 'segmentCount': 0}
    ordered = [messages[key] for key in sorted(messages, key=_attribute_sort_key)]
    return {
        'active': True,
        'attributes': ordered,
        'messages': [record['message'] for record in ordered],
        'segmentCount': segment_count,
    }


__all__ = [
    'actor_display_name',
    'clear_segment_review_if_resolved',
    'deletion_banner_message',
    'deletion_date_label',
    'deletion_detail',
    'mark_segments_for_deleted_attributes',
    'review_notice',
    'segment_deleted_attribute_ids',
    'segments_needing_review',
    'serialize_deletion_records',
]
