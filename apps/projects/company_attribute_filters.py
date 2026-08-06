from __future__ import annotations

import hashlib
import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, TypeAlias

from django.core.cache import cache as application_cache
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef, QuerySet
from django.http import QueryDict

from .models import (
    COMPANY_ATTRIBUTE_OPTION_COLOR_PALETTE,
    CompanyAttribute,
    CompanyAttributeMoneyCurrency,
    CompanyAttributeOption,
    CompanyAttributeType,
    CompanyAttributeValue,
)


FILTER_HASH_VERSION = 1
DEFAULT_FILTERS_HASH = "default"
MAX_FILTER_ROWS = 64
MAX_SELECT_VALUES = 100
MAX_TEXT_FILTER_LENGTH = 500
MAX_FILTER_PARAMETER_VALUES = 512
MAX_SCALAR_PARAMETER_LENGTH = 1_000
MAX_DATABASE_ID = 9_223_372_036_854_775_807
FILTER_ATTRIBUTE_APPLICATION_CACHE_SECONDS = 60 * 60


logger = logging.getLogger(__name__)

_PARAMETER_RE = re.compile(r"^ca\.([0-9]{1,20})\.(op|value|min|max|from|to)$")
_PARAMETER_FIELDS = ("op", "value", "min", "max", "from", "to")

OPERATOR_LABELS = {
    "in": "is one of",
    "not_in": "is not one of",
    "eq": "equals",
    "neq": "is not",
    "gt": "greater than",
    "gte": "greater than or equal to",
    "lt": "less than",
    "lte": "less than or equal to",
    "between": "between",
    "contains": "contains",
    "not_contains": "does not contain",
    "on": "on",
    "before": "before",
    "after": "after",
    "empty": "is empty",
    "not_empty": "is not empty",
}

OPERATORS_BY_TYPE = {
    CompanyAttributeType.SINGLE_SELECT: ("in", "not_in", "empty", "not_empty"),
    CompanyAttributeType.MONEY: ("eq", "gt", "gte", "lt", "lte", "between", "empty", "not_empty"),
    CompanyAttributeType.NUMBER: ("eq", "gt", "gte", "lt", "lte", "between", "empty", "not_empty"),
    CompanyAttributeType.TEXT: ("contains", "not_contains", "eq", "neq", "empty", "not_empty"),
    CompanyAttributeType.DATE: ("on", "before", "after", "between", "empty", "not_empty"),
    CompanyAttributeType.BOOLEAN: ("eq",),
}

OPERATOR_LABELS_BY_TYPE = {
    CompanyAttributeType.SINGLE_SELECT: {
        "in": "is one of",
        "not_in": "is not one of",
        "empty": "is empty",
        "not_empty": "is not empty",
    },
    CompanyAttributeType.MONEY: {
        code: OPERATOR_LABELS[code]
        for code in ("eq", "gt", "gte", "lt", "lte", "between", "empty", "not_empty")
    },
    CompanyAttributeType.NUMBER: {
        code: OPERATOR_LABELS[code]
        for code in ("eq", "gt", "gte", "lt", "lte", "between", "empty", "not_empty")
    },
    CompanyAttributeType.TEXT: {
        "contains": "contains",
        "not_contains": "does not contain",
        "eq": "is",
        "neq": "is not",
        "empty": "is empty",
        "not_empty": "is not empty",
    },
    CompanyAttributeType.DATE: {
        code: OPERATOR_LABELS[code]
        for code in ("on", "before", "after", "between", "empty", "not_empty")
    },
    CompanyAttributeType.BOOLEAN: {"eq": "is"},
}

_CURRENCY_SYMBOLS = {
    CompanyAttributeMoneyCurrency.USD: "$",
    CompanyAttributeMoneyCurrency.EUR: "€",
    CompanyAttributeMoneyCurrency.GBP: "£",
}

FilterScalar: TypeAlias = str | int | Decimal | date | bool
_current_company_attribute_filter_state: ContextVar[CompanyAttributeFilterState | None] = (
    ContextVar("current_company_attribute_filter_state", default=None)
)
_current_company_cohort: ContextVar[frozenset[str] | None] = (
    ContextVar("current_company_cohort", default=None)
)


@dataclass(frozen=True)
class CompanyAttributeFilterIssue:
    attribute_id: int | None
    field: str
    code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "attribute_id": self.attribute_id,
            "field": self.field,
            "code": self.code,
            "message": self.message,
        }


class CompanyAttributeFilterValidationError(Exception):
    """Raised when strict parsing finds an incomplete or invalid filter row."""

    def __init__(
        self,
        issues: tuple[CompanyAttributeFilterIssue, ...],
        state: CompanyAttributeFilterState | None = None,
    ):
        self.issues = issues
        self.errors = [issue.to_dict() for issue in issues]
        self.state = state
        super().__init__("Company attribute filters could not be validated.")


@dataclass(frozen=True)
class CompanyAttributeFilter:
    attribute_id: int
    attribute_name: str
    attribute_type: str
    operator: str
    values: tuple[FilterScalar, ...] = ()
    option_labels: tuple[tuple[int, str], ...] = ()
    currency: str = ""

    @property
    def value(self) -> FilterScalar | None:
        return self.values[0] if self.values else None

    @property
    def lower(self) -> Decimal | date | None:
        value = self.values[0] if self.operator == "between" and self.values else None
        return value if isinstance(value, (Decimal, date)) else None

    @property
    def upper(self) -> Decimal | date | None:
        value = self.values[1] if self.operator == "between" and len(self.values) > 1 else None
        return value if isinstance(value, (Decimal, date)) else None

    @property
    def canonical_pairs(self) -> tuple[tuple[str, str], ...]:
        prefix = f"ca.{self.attribute_id}"
        pairs: list[tuple[str, str]] = [(f"{prefix}.op", self.operator)]
        if self.operator == "between":
            if self.attribute_type in (CompanyAttributeType.NUMBER, CompanyAttributeType.MONEY):
                pairs.extend(
                    (
                        (f"{prefix}.min", _serialize_scalar(self.values[0])),
                        (f"{prefix}.max", _serialize_scalar(self.values[1])),
                    )
                )
            else:
                pairs.extend(
                    (
                        (f"{prefix}.from", _serialize_scalar(self.values[0])),
                        (f"{prefix}.to", _serialize_scalar(self.values[1])),
                    )
                )
        elif self.operator not in ("empty", "not_empty"):
            pairs.extend((f"{prefix}.value", _serialize_scalar(value)) for value in self.values)
        return tuple(pairs)

    @property
    def summary(self) -> str:
        if self.operator == "empty":
            return f"{self.attribute_name} is empty"
        if self.operator == "not_empty":
            return f"{self.attribute_name} is not empty"
        if self.attribute_type == CompanyAttributeType.SINGLE_SELECT:
            labels_by_id = dict(self.option_labels)
            labels = ", ".join(labels_by_id.get(int(value), str(value)) for value in self.values)
            if self.operator == "in":
                return f"{self.attribute_name}: {labels}"
            return f"{self.attribute_name} is not one of {labels}"
        if self.attribute_type == CompanyAttributeType.BOOLEAN:
            return f"{self.attribute_name}: {'Yes' if self.value is True else 'No'}"

        rendered = tuple(self._display_scalar(value) for value in self.values)
        if self.operator == "between":
            return f"{self.attribute_name}: {rendered[0]}–{rendered[1]}"
        if self.operator in ("eq", "on"):
            return f"{self.attribute_name}: {rendered[0]}"
        symbols = {
            "neq": "≠",
            "gt": ">",
            "gte": "≥",
            "lt": "<",
            "lte": "≤",
            "before": "before",
            "after": "after",
            "contains": "contains",
            "not_contains": "does not contain",
        }
        return f"{self.attribute_name} {symbols[self.operator]} {rendered[0]}"

    def _display_scalar(self, value: FilterScalar) -> str:
        rendered = _serialize_scalar(value)
        if self.attribute_type == CompanyAttributeType.MONEY:
            return f"{_CURRENCY_SYMBOLS.get(self.currency, f'{self.currency} ')}{rendered}"
        return rendered

    def to_payload(self) -> dict[str, Any]:
        return {
            "attribute_id": self.attribute_id,
            "attribute_name": self.attribute_name,
            "attribute_type": self.attribute_type,
            "operator": self.operator,
            "values": [_serialize_scalar(value) for value in self.values],
            "option_labels": [
                {"id": option_id, "label": label} for option_id, label in self.option_labels
            ],
            "currency": self.currency,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class CompanyAttributeFilterState:
    project_id: int
    filters: tuple[CompanyAttributeFilter, ...] = ()
    issues: tuple[CompanyAttributeFilterIssue, ...] = ()
    _stable_hash: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        payload = json.dumps(
            {
                "version": FILTER_HASH_VERSION,
                "pairs": self.canonical_pairs,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        object.__setattr__(self, "_stable_hash", hashlib.sha256(payload.encode("utf-8")).hexdigest())

    @property
    def active(self) -> bool:
        return bool(self.filters)

    @property
    def active_count(self) -> int:
        return len(self.filters)

    @property
    def canonical_pairs(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            pair
            for item in sorted(self.filters, key=lambda candidate: candidate.attribute_id)
            for pair in item.canonical_pairs
        )

    @property
    def summaries(self) -> tuple[str, ...]:
        return tuple(item.summary for item in self.filters)

    @property
    def stable_hash(self) -> str:
        return self._stable_hash

    @property
    def filters_hash(self) -> str:
        return self.stable_hash if self.active else DEFAULT_FILTERS_HASH

    @property
    def applied(self) -> dict[str, dict[str, Any]]:
        return serialize_company_attribute_filter_state(self)

    def to_payload(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "active_count": self.active_count,
            "canonical_pairs": [list(pair) for pair in self.canonical_pairs],
            "stable_hash": self.stable_hash,
            "filters_hash": self.filters_hash,
            "summaries": list(self.summaries),
            "filters": [item.to_payload() for item in self.filters],
            "applied": self.applied,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def parse_company_attribute_filters(
    project: Any,
    params: Mapping[str, Any],
    *,
    strict: bool = False,
    attributes: Iterable[CompanyAttribute] | None = None,
) -> CompanyAttributeFilterState:
    """
    Parse URL filter state for one project.

    Strict mode rejects the complete draft when any row is invalid. Lenient mode
    keeps valid rows, omits malformed/stale references, and exposes issues so the
    caller can canonicalize the URL without returning a server error.
    """

    project_id = _project_id(project)
    groups: dict[int, dict[str, list[Any]]] = {}
    issues: list[CompanyAttributeFilterIssue] = []
    parameter_value_count = 0
    fatal = False

    for raw_key in params.keys():
        key = str(raw_key)
        if not key.startswith("ca."):
            continue
        values = _getlist(params, raw_key)
        parameter_value_count += len(values)
        match = _PARAMETER_RE.fullmatch(key)
        if match is None:
            issues.append(_issue(None, key, "malformed_parameter", "This filter parameter is malformed."))
            continue
        attribute_id = int(match.group(1))
        if not 0 < attribute_id <= MAX_DATABASE_ID:
            issues.append(_issue(None, key, "invalid_attribute", "Enter a valid attribute ID."))
            continue
        groups.setdefault(attribute_id, {}).setdefault(match.group(2), []).extend(values)

    if parameter_value_count > MAX_FILTER_PARAMETER_VALUES:
        issues.append(
            _issue(
                None,
                "filters",
                "too_many_parameters",
                f"Use no more than {MAX_FILTER_PARAMETER_VALUES} company attribute filter values.",
            )
        )
        fatal = True
    if len(groups) > MAX_FILTER_ROWS:
        issues.append(
            _issue(
                None,
                "filters",
                "too_many_filters",
                f"Use no more than {MAX_FILTER_ROWS} company attribute filters.",
            )
        )
        fatal = True

    if attributes is None:
        attribute_rows = (
            CompanyAttribute.objects.filter(project_id=project_id, id__in=groups)
            .prefetch_related("options")
            .order_by("id")
        )
    else:
        attribute_rows = (
            attribute
            for attribute in attributes
            if attribute.project_id == project_id and attribute.id in groups
        )
    attributes_by_id = {
        attribute.id: attribute
        for attribute in attribute_rows
    }
    parsed: list[CompanyAttributeFilter] = []
    if not fatal:
        for attribute_id in sorted(groups):
            attribute = attributes_by_id.get(attribute_id)
            if attribute is None:
                issues.append(
                    _issue(
                        attribute_id,
                        "attribute_id",
                        "unknown_attribute",
                        "This attribute does not belong to the project.",
                    )
                )
                continue
            item, item_issues = _parse_filter_row(attribute, groups[attribute_id], strict=strict)
            issues.extend(item_issues)
            if item is not None:
                parsed.append(item)

    state = CompanyAttributeFilterState(
        project_id=project_id,
        filters=tuple(parsed),
        issues=tuple(issues),
    )
    if strict and issues:
        raise CompanyAttributeFilterValidationError(tuple(issues), state=state)
    return state


def apply_company_attribute_filters(
    queryset: QuerySet,
    state: CompanyAttributeFilterState,
    company_field: str = "company_id",
) -> QuerySet:
    """
    Apply one correlated EXISTS/NOT EXISTS predicate per active attribute.

    The inactive path returns the original queryset unchanged. On the active
    path null/blank identities are deliberately excluded.
    """

    if not state.active:
        return queryset
    if not company_field or company_field.startswith("_"):
        raise ValueError("company_field must name a queryset field or annotation.")

    queryset = queryset.filter(**{f"{company_field}__isnull": False}).exclude(**{company_field: ""})
    for item in state.filters:
        base_values = CompanyAttributeValue.objects.filter(
            attribute_id=item.attribute_id,
            attribute__project_id=state.project_id,
            company_id=OuterRef(company_field),
        )
        nonempty_values = _nonempty_values(base_values, item.attribute_type)

        if item.operator == "empty":
            queryset = queryset.filter(~Exists(nonempty_values))
            continue
        if item.operator == "not_empty":
            queryset = queryset.filter(Exists(nonempty_values))
            continue

        matching_values = _matching_values(base_values, item)
        if item.operator in ("not_in", "not_contains", "neq"):
            queryset = queryset.filter(Exists(nonempty_values)).filter(~Exists(matching_values))
        else:
            queryset = queryset.filter(Exists(matching_values))
    return queryset


def resolve_company_cohort(
    state: CompanyAttributeFilterState,
    observed_company_ids: Iterable[str],
) -> set[str]:
    """
    Narrow an observed company universe to the identities an active state selects.

    Overview builders need one concrete cohort per variant, and they need it to
    survive an all-``is empty`` filter set. ``resolve_matching_company_ids``
    cannot supply that: it anchors on the first non-``empty`` row and returns
    ``None`` when there is none, which callers read as "nothing matches".

    Starting from the companies observed in the requested window instead lets
    ``is empty`` mean "observed, and carrying no value for this attribute". Each
    row narrows the cohort with the same operator semantics
    ``apply_company_attribute_filters`` applies, but as set algebra over one
    indexed lookup per filter rather than a correlated subquery per fact row.
    """

    if not state.active:
        raise ValueError("Company cohorts are only defined for an active filter state.")

    cohort = {str(company_id) for company_id in observed_company_ids if str(company_id or "").strip()}
    for item in state.filters:
        if not cohort:
            break
        base_values = CompanyAttributeValue.objects.filter(
            attribute_id=item.attribute_id,
            attribute__project_id=state.project_id,
        )
        nonempty_ids = set(
            _nonempty_values(base_values, item.attribute_type)
            .order_by()
            .values_list("company_id", flat=True)
        )

        if item.operator == "empty":
            cohort -= nonempty_ids
            continue
        if item.operator == "not_empty":
            cohort &= nonempty_ids
            continue

        matching_ids = set(
            _matching_values(base_values, item)
            .order_by()
            .values_list("company_id", flat=True)
        )
        if item.operator in ("not_in", "not_contains", "neq"):
            cohort = (cohort & nonempty_ids) - matching_ids
        else:
            cohort &= matching_ids
    return cohort


def resolve_company_cohorts(
    states: Iterable[CompanyAttributeFilterState],
    observed_company_ids: Iterable[str],
) -> list[set[str]]:
    """
    Resolve several filter states against one observed universe.

    Saved segments overlap heavily — the same attribute row usually appears in
    several of them — so the per-row lookups are memoized and the observed
    universe is materialized once. That keeps a list of N segments at a handful
    of indexed queries instead of N cohort resolutions.
    """

    universe = {
        str(company_id)
        for company_id in observed_company_ids
        if str(company_id or "").strip()
    }
    nonempty_cache: dict[tuple[int, str], set[str]] = {}
    matching_cache: dict[tuple[str, ...], set[str]] = {}

    def nonempty_ids(item: CompanyAttributeFilter, project_id: int) -> set[str]:
        key = (item.attribute_id, item.attribute_type)
        if key not in nonempty_cache:
            nonempty_cache[key] = set(
                _nonempty_values(_segment_values(item, project_id), item.attribute_type)
                .order_by()
                .values_list("company_id", flat=True)
            )
        return nonempty_cache[key]

    def matching_ids(item: CompanyAttributeFilter, project_id: int) -> set[str]:
        key = (str(project_id),) + tuple(f"{name}={value}" for name, value in item.canonical_pairs)
        if key not in matching_cache:
            matching_cache[key] = set(
                _matching_values(_segment_values(item, project_id), item)
                .order_by()
                .values_list("company_id", flat=True)
            )
        return matching_cache[key]

    cohorts: list[set[str]] = []
    for state in states:
        if not state.active:
            cohorts.append(set(universe))
            continue
        cohort = set(universe)
        for item in state.filters:
            if not cohort:
                break
            if item.operator == "empty":
                cohort -= nonempty_ids(item, state.project_id)
                continue
            if item.operator == "not_empty":
                cohort &= nonempty_ids(item, state.project_id)
                continue
            if item.operator in ("not_in", "not_contains", "neq"):
                cohort = (cohort & nonempty_ids(item, state.project_id)) - matching_ids(
                    item,
                    state.project_id,
                )
            else:
                cohort &= matching_ids(item, state.project_id)
        cohorts.append(cohort)
    return cohorts


def _segment_values(item: CompanyAttributeFilter, project_id: int) -> QuerySet:
    return CompanyAttributeValue.objects.filter(
        attribute_id=item.attribute_id,
        attribute__project_id=project_id,
    )


def company_attribute_query_from_definition(definition: Mapping[str, Any]) -> QueryDict:
    """Expand a stored filter definition back into its ``ca.*`` query state."""

    query = QueryDict("", mutable=True)
    if not isinstance(definition, Mapping):
        return query
    for raw_attribute_id, raw_clause in definition.items():
        attribute_id = str(raw_attribute_id or "").strip()
        if not attribute_id.isdigit() or not isinstance(raw_clause, Mapping):
            continue
        operator = str(raw_clause.get("op") or "").strip()
        if not operator:
            continue
        prefix = f"ca.{attribute_id}"
        query.appendlist(f"{prefix}.op", operator)
        values = raw_clause.get("values")
        if isinstance(values, (list, tuple)):
            for value in values:
                query.appendlist(f"{prefix}.value", _definition_scalar(value))
        for field_name in ("value", "min", "max", "from", "to"):
            value = raw_clause.get(field_name)
            if value is None:
                continue
            query.appendlist(f"{prefix}.{field_name}", _definition_scalar(value))
    return query


def filter_state_from_definition(
    project: Any,
    definition: Mapping[str, Any],
    *,
    strict: bool = False,
    attributes: Iterable[CompanyAttribute] | None = None,
) -> CompanyAttributeFilterState:
    """Parse a stored filter definition with the same rules as URL filter state."""

    return parse_company_attribute_filters(
        project,
        company_attribute_query_from_definition(definition),
        strict=strict,
        attributes=attributes,
    )


def _definition_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@contextmanager
def company_attribute_filter_scope(
    state: CompanyAttributeFilterState | None,
    *,
    cohort: Iterable[str] | None = None,
):
    """
    Make one immutable filter state available to nested analytics builders.

    A builder that has already resolved the state to concrete company IDs passes
    them as *cohort*. Nested queries then narrow by an indexed ``company_id IN``
    instead of re-deriving the same answer as a correlated subquery per fact row.
    """

    token = _current_company_attribute_filter_state.set(state)
    cohort_token = _current_company_cohort.set(
        None if cohort is None else frozenset(cohort),
    )
    try:
        yield state
    finally:
        _current_company_cohort.reset(cohort_token)
        _current_company_attribute_filter_state.reset(token)


def current_company_attribute_filter_state() -> CompanyAttributeFilterState | None:
    return _current_company_attribute_filter_state.get()


def current_company_cohort() -> frozenset[str] | None:
    """Company IDs the enclosing scope already resolved, when it resolved them."""

    return _current_company_cohort.get()


def narrow_queryset_to_current_company_filters(
    queryset: QuerySet,
    company_field: str = "company_id",
) -> QuerySet:
    """
    Restrict *queryset* to the enclosing scope's companies.

    Prefers the pre-resolved cohort and falls back to per-row subqueries only
    when no builder resolved one.
    """

    state = current_company_attribute_filter_state()
    if state is None or not state.active:
        return queryset
    cohort = current_company_cohort()
    if cohort is None:
        return apply_company_attribute_filters(queryset, state, company_field=company_field)
    return queryset.filter(**{f"{company_field}__in": cohort})


def serialize_company_attribute_filter_state(
    state: CompanyAttributeFilterState,
) -> dict[str, dict[str, Any]]:
    """Serialize applied rows for dialog hydration without mutable display keys."""

    applied: dict[str, dict[str, Any]] = {}
    for item in state.filters:
        value: dict[str, Any] = {"op": item.operator}
        if item.operator == "between":
            if item.attribute_type in (CompanyAttributeType.NUMBER, CompanyAttributeType.MONEY):
                value["min"] = _serialize_scalar(item.values[0])
                value["max"] = _serialize_scalar(item.values[1])
            else:
                value["from"] = _serialize_scalar(item.values[0])
                value["to"] = _serialize_scalar(item.values[1])
        elif item.operator not in ("empty", "not_empty"):
            serialized_values = [_serialize_scalar(raw_value) for raw_value in item.values]
            if item.attribute_type == CompanyAttributeType.SINGLE_SELECT:
                value["values"] = serialized_values
            else:
                value["value"] = serialized_values[0]
        applied[str(item.attribute_id)] = value
    return applied


def load_company_attribute_filter_attributes(
    project: Any,
) -> tuple[CompanyAttribute, ...]:
    project_id = _project_id(project)
    revision = (
        project.get("filtered_analytics_revision")
        if isinstance(project, dict)
        else getattr(project, "filtered_analytics_revision", None)
    )
    cache_key = None
    if revision is not None:
        cache_key = (
            "company-filter-attributes:"
            f"v1:{project_id}:r{int(revision)}"
        )
        try:
            cached = application_cache.get(cache_key)
        except Exception:
            logger.exception(
                "Could not read company filter attributes from the "
                "application cache.",
                extra={"project_id": project_id},
            )
            cached = None
        if isinstance(cached, tuple):
            return cached

    attributes = tuple(
        CompanyAttribute.objects.filter(project_id=_project_id(project))
        .prefetch_related("options")
        .order_by("position", "id")
    )
    if cache_key is not None:
        try:
            application_cache.set(
                cache_key,
                attributes,
                timeout=FILTER_ATTRIBUTE_APPLICATION_CACHE_SECONDS,
            )
        except Exception:
            logger.exception(
                "Could not store company filter attributes in the "
                "application cache.",
                extra={"project_id": project_id},
            )
    return attributes


def serialize_company_attribute_filter_metadata(
    project: Any,
    state: CompanyAttributeFilterState,
    *,
    attributes: Iterable[CompanyAttribute] | None = None,
) -> dict[str, Any]:
    """Return project-scoped filter definitions plus the currently applied state."""

    project_id = _project_id(project)
    if state.project_id != project_id:
        raise ValueError("Filter state belongs to a different project.")
    if attributes is None:
        attributes = (
            CompanyAttribute.objects.filter(project_id=project_id)
            .prefetch_related("options")
            .order_by("position", "id")
        )
    else:
        attributes = sorted(
            (
                attribute
                for attribute in attributes
                if attribute.project_id == project_id
            ),
            key=lambda attribute: (attribute.position, attribute.id),
        )
    serialized_attributes = []
    for attribute in attributes:
        serialized_attributes.append(
            {
                "id": attribute.id,
                "name": attribute.name,
                "type": attribute.attribute_type,
                "type_label": (
                    "Select"
                    if attribute.attribute_type == CompanyAttributeType.SINGLE_SELECT
                    else attribute.get_attribute_type_display()
                ),
                "currency": attribute.currency,
                "operators": [
                    {
                        "code": operator,
                        "label": OPERATOR_LABELS_BY_TYPE[attribute.attribute_type][operator],
                    }
                    for operator in OPERATORS_BY_TYPE[attribute.attribute_type]
                ],
                "options": [
                    {
                        "id": option.id,
                        "label": option.label,
                        "color": dict(
                            COMPANY_ATTRIBUTE_OPTION_COLOR_PALETTE.get(option.color, {})
                        ),
                    }
                    for option in attribute.options.all()
                ],
            }
        )
    return {
        "attributes": serialized_attributes,
        "state": state.to_payload(),
    }


build_company_attribute_filter_payload = serialize_company_attribute_filter_metadata


def canonicalize_company_attribute_query(
    params: Mapping[str, Any],
    state: CompanyAttributeFilterState,
    *,
    reset_page: bool = False,
) -> QueryDict:
    """Replace only ``ca.*`` state while preserving unrelated repeated values."""

    result = QueryDict("", mutable=True)
    for raw_key in params.keys():
        key = str(raw_key)
        if key.startswith("ca.") or (reset_page and key == "page"):
            continue
        result.setlist(key, [str(value) for value in _getlist(params, raw_key)])
    for key, value in state.canonical_pairs:
        result.appendlist(key, value)
    return result


def canonical_company_attribute_query_if_needed(
    params: Mapping[str, Any],
    state: CompanyAttributeFilterState,
    *,
    reset_page: bool = False,
) -> QueryDict | None:
    """Return canonical query state only when submitted ``ca.*`` pairs differ.

    Overview views use this to remove malformed or stale references and to
    normalize ordering/typed values before the URL can imply a cohort that the
    server did not actually apply.
    """

    submitted_pairs = tuple(
        (str(raw_key), str(value))
        for raw_key in params.keys()
        if str(raw_key).startswith("ca.")
        for value in _getlist(params, raw_key)
    )
    if submitted_pairs == state.canonical_pairs:
        return None
    return canonicalize_company_attribute_query(
        params,
        state,
        reset_page=reset_page,
    )


def clear_company_attribute_query(
    params: Mapping[str, Any],
    *,
    reset_page: bool = False,
) -> QueryDict:
    return canonicalize_company_attribute_query(
        params,
        CompanyAttributeFilterState(project_id=0),
        reset_page=reset_page,
    )


def _parse_filter_row(
    attribute: CompanyAttribute,
    fields: dict[str, list[Any]],
    *,
    strict: bool,
) -> tuple[CompanyAttributeFilter | None, list[CompanyAttributeFilterIssue]]:
    issues: list[CompanyAttributeFilterIssue] = []
    operator_values = fields.get("op", [])
    if len(operator_values) != 1:
        issues.append(
            _issue(
                attribute.id,
                "op",
                "invalid_operator_count",
                "Select exactly one operator.",
            )
        )
        return None, issues
    try:
        operator = _bounded_string(operator_values[0], MAX_SCALAR_PARAMETER_LENGTH).strip().lower()
    except (TypeError, ValueError):
        issues.append(_issue(attribute.id, "op", "invalid_operator", "Select a valid operator."))
        return None, issues
    if operator not in OPERATORS_BY_TYPE.get(attribute.attribute_type, ()):
        issues.append(_issue(attribute.id, "op", "invalid_operator", "Select a valid operator."))
        return None, issues

    allowed_fields = {"op"}
    if operator == "between":
        if attribute.attribute_type in (CompanyAttributeType.NUMBER, CompanyAttributeType.MONEY):
            allowed_fields.update(("min", "max"))
        else:
            allowed_fields.update(("from", "to"))
    elif operator not in ("empty", "not_empty"):
        allowed_fields.add("value")

    if strict:
        for field_name in _PARAMETER_FIELDS:
            if field_name not in allowed_fields and fields.get(field_name):
                issues.append(
                    _issue(
                        attribute.id,
                        field_name,
                        "unexpected_value",
                        "Remove the value that is not used by this operator.",
                    )
                )

    if operator in ("empty", "not_empty"):
        return _filter_from_attribute(attribute, operator), issues
    if attribute.attribute_type == CompanyAttributeType.SINGLE_SELECT:
        item, select_issues = _parse_select_filter(attribute, operator, fields.get("value", []))
        issues.extend(select_issues)
        return item, issues
    if operator == "between":
        if attribute.attribute_type in (CompanyAttributeType.NUMBER, CompanyAttributeType.MONEY):
            lower_field, upper_field = "min", "max"
            parser = _parse_decimal
        else:
            lower_field, upper_field = "from", "to"
            parser = _parse_date
        lower = _parse_single_value(attribute.id, lower_field, fields.get(lower_field, []), parser, issues)
        upper = _parse_single_value(attribute.id, upper_field, fields.get(upper_field, []), parser, issues)
        if lower is None or upper is None:
            return None, issues
        if lower > upper:
            issues.append(
                _issue(
                    attribute.id,
                    upper_field,
                    "invalid_range",
                    "The lower bound cannot be greater than the upper bound.",
                )
            )
            return None, issues
        return _filter_from_attribute(attribute, operator, (lower, upper)), issues

    parser = {
        CompanyAttributeType.TEXT: _parse_text,
        CompanyAttributeType.NUMBER: _parse_decimal,
        CompanyAttributeType.MONEY: _parse_decimal,
        CompanyAttributeType.DATE: _parse_date,
        CompanyAttributeType.BOOLEAN: _parse_boolean,
    }[attribute.attribute_type]
    value = _parse_single_value(attribute.id, "value", fields.get("value", []), parser, issues)
    if value is None:
        return None, issues
    return _filter_from_attribute(attribute, operator, (value,)), issues


def _parse_select_filter(
    attribute: CompanyAttribute,
    operator: str,
    raw_values: list[Any],
) -> tuple[CompanyAttributeFilter | None, list[CompanyAttributeFilterIssue]]:
    issues: list[CompanyAttributeFilterIssue] = []
    if not raw_values:
        issues.append(_issue(attribute.id, "value", "required", "Select at least one option."))
        return None, issues
    if len(raw_values) > MAX_SELECT_VALUES:
        issues.append(
            _issue(
                attribute.id,
                "value",
                "too_many_values",
                f"Select no more than {MAX_SELECT_VALUES} options.",
            )
        )
        return None, issues

    options_by_id = {option.id: option for option in attribute.options.all()}
    selected: dict[int, CompanyAttributeOption] = {}
    for raw_value in raw_values:
        option_id = _positive_id(raw_value)
        option = options_by_id.get(option_id) if option_id is not None else None
        if option is None:
            issues.append(
                _issue(
                    attribute.id,
                    "value",
                    "unknown_option",
                    "This option does not belong to the attribute.",
                )
            )
            continue
        selected[option.id] = option
    if not selected:
        if not issues:
            issues.append(_issue(attribute.id, "value", "required", "Select at least one option."))
        return None, issues
    option_ids = tuple(sorted(selected))
    return (
        _filter_from_attribute(
            attribute,
            operator,
            option_ids,
            option_labels=tuple((option_id, selected[option_id].label) for option_id in option_ids),
        ),
        issues,
    )


def _parse_single_value(
    attribute_id: int,
    field_name: str,
    raw_values: list[Any],
    parser: Any,
    issues: list[CompanyAttributeFilterIssue],
) -> FilterScalar | None:
    if len(raw_values) != 1:
        issues.append(
            _issue(
                attribute_id,
                field_name,
                "required" if not raw_values else "multiple_values",
                "Enter exactly one value.",
            )
        )
        return None
    try:
        return parser(raw_values[0])
    except (TypeError, ValueError, ValidationError):
        issues.append(_issue(attribute_id, field_name, "invalid_value", "Enter a valid value."))
        return None


def _filter_from_attribute(
    attribute: CompanyAttribute,
    operator: str,
    values: tuple[FilterScalar, ...] = (),
    *,
    option_labels: tuple[tuple[int, str], ...] = (),
) -> CompanyAttributeFilter:
    return CompanyAttributeFilter(
        attribute_id=attribute.id,
        attribute_name=attribute.name,
        attribute_type=attribute.attribute_type,
        operator=operator,
        values=values,
        option_labels=option_labels,
        currency=attribute.currency,
    )


def _nonempty_values(queryset: QuerySet, attribute_type: str) -> QuerySet:
    if attribute_type == CompanyAttributeType.TEXT:
        return queryset.filter(text_value__isnull=False).exclude(text_value="")
    field_name = {
        CompanyAttributeType.NUMBER: "decimal_value",
        CompanyAttributeType.MONEY: "decimal_value",
        CompanyAttributeType.DATE: "date_value",
        CompanyAttributeType.BOOLEAN: "boolean_value",
        CompanyAttributeType.SINGLE_SELECT: "option_id",
    }[attribute_type]
    return queryset.filter(**{f"{field_name}__isnull": False})


def _matching_values(queryset: QuerySet, item: CompanyAttributeFilter) -> QuerySet:
    if item.attribute_type == CompanyAttributeType.SINGLE_SELECT:
        return queryset.filter(option_id__in=item.values)
    if item.attribute_type == CompanyAttributeType.TEXT:
        lookup = {
            "contains": "text_value__icontains",
            "not_contains": "text_value__icontains",
            "eq": "text_value__iexact",
            "neq": "text_value__iexact",
        }[item.operator]
        return queryset.filter(**{lookup: item.value})
    if item.attribute_type in (CompanyAttributeType.NUMBER, CompanyAttributeType.MONEY):
        if item.operator == "between":
            return queryset.filter(decimal_value__gte=item.values[0], decimal_value__lte=item.values[1])
        lookup = {
            "eq": "decimal_value",
            "gt": "decimal_value__gt",
            "gte": "decimal_value__gte",
            "lt": "decimal_value__lt",
            "lte": "decimal_value__lte",
        }[item.operator]
        return queryset.filter(**{lookup: item.value})
    if item.attribute_type == CompanyAttributeType.DATE:
        if item.operator == "between":
            return queryset.filter(date_value__gte=item.values[0], date_value__lte=item.values[1])
        lookup = {
            "on": "date_value",
            "before": "date_value__lt",
            "after": "date_value__gt",
        }[item.operator]
        return queryset.filter(**{lookup: item.value})
    if item.attribute_type == CompanyAttributeType.BOOLEAN:
        return queryset.filter(boolean_value=item.value)
    raise ValueError(f"Unsupported company attribute type: {item.attribute_type}")


def _parse_text(raw: Any) -> str:
    value = _bounded_string(raw, MAX_TEXT_FILTER_LENGTH).strip()
    if not value or "\x00" in value:
        raise ValueError
    return value


def _parse_decimal(raw: Any) -> Decimal:
    value_string = _bounded_string(raw, MAX_SCALAR_PARAMETER_LENGTH).strip()
    try:
        value = Decimal(value_string)
    except (InvalidOperation, ValueError):
        raise ValueError from None
    if not value.is_finite():
        raise ValueError
    field = CompanyAttributeValue._meta.get_field("decimal_value")
    value = field.clean(value, None)
    return Decimal(0) if value.is_zero() else value


def _parse_date(raw: Any) -> date:
    value_string = _bounded_string(raw, 32).strip()
    try:
        value = date.fromisoformat(value_string)
    except ValueError:
        raise ValueError from None
    if value.isoformat() != value_string:
        raise ValueError
    return value


def _parse_boolean(raw: Any) -> bool:
    value = _bounded_string(raw, 16).strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError


def _serialize_scalar(value: FilterScalar) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        rendered = format(value, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        return rendered or "0"
    return str(value)


def _positive_id(raw: Any) -> int | None:
    try:
        value_string = _bounded_string(raw, 20).strip()
    except (TypeError, ValueError):
        return None
    if not value_string.isdigit():
        return None
    value = int(value_string)
    return value if 0 < value <= MAX_DATABASE_ID else None


def _bounded_string(raw: Any, max_length: int) -> str:
    if isinstance(raw, str):
        value = raw
    elif raw is None or isinstance(raw, (dict, list, tuple, set)):
        raise ValueError
    else:
        value = str(raw)
    if len(value) > max_length:
        raise ValueError
    return value


def _getlist(params: Mapping[str, Any], key: Any) -> list[Any]:
    getlist = getattr(params, "getlist", None)
    if callable(getlist):
        return list(getlist(key))
    value = params.get(key)
    if isinstance(value, (list, tuple)):
        return list(value)
    return [] if value is None else [value]


def _project_id(project: Any) -> int:
    project_id = getattr(project, "pk", None)
    if project_id is None:
        project_id = getattr(project, "id", project)
    if isinstance(project_id, bool):
        raise ValueError("A saved project is required.")
    try:
        project_id = int(project_id)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("A saved project is required.") from None
    if project_id <= 0:
        raise ValueError("A saved project is required.")
    return project_id


def _issue(
    attribute_id: int | None,
    field_name: str,
    code: str,
    message: str,
) -> CompanyAttributeFilterIssue:
    return CompanyAttributeFilterIssue(
        attribute_id=attribute_id,
        field=field_name,
        code=code,
        message=message,
    )


MAX_MATERIALIZED_COMPANY_COHORT = 100_000


def resolve_matching_company_ids(
    state: CompanyAttributeFilterState,
):
    from apps.projects.models import CompanyAttributeValue
    anchor = next(
        (item for item in state.filters if item.operator != "empty"),
        None,
    )
    if anchor is None:
        return None
    candidates = CompanyAttributeValue.objects.filter(
        attribute_id=anchor.attribute_id,
    )

    matching_ids = (
        apply_company_attribute_filters(
            candidates,
            state,
            company_field="company_id",
        )
        .order_by()
        .values_list("company_id", flat=True)
        .distinct()
    )
    bounded_ids = tuple(matching_ids[: MAX_MATERIALIZED_COMPANY_COHORT + 1])
    if len(bounded_ids) > MAX_MATERIALIZED_COMPANY_COHORT:
        return matching_ids
    return bounded_ids


__all__ = [
    "DEFAULT_FILTERS_HASH",
    "FILTER_HASH_VERSION",
    "MAX_FILTER_ROWS",
    "MAX_SELECT_VALUES",
    "MAX_TEXT_FILTER_LENGTH",
    "OPERATOR_LABELS",
    "OPERATOR_LABELS_BY_TYPE",
    "OPERATORS_BY_TYPE",
    "CompanyAttributeFilter",
    "CompanyAttributeFilterIssue",
    "CompanyAttributeFilterState",
    "CompanyAttributeFilterValidationError",
    "apply_company_attribute_filters",
    "build_company_attribute_filter_payload",
    "canonical_company_attribute_query_if_needed",
    "canonicalize_company_attribute_query",
    "clear_company_attribute_query",
    "company_attribute_filter_scope",
    "company_attribute_query_from_definition",
    "current_company_attribute_filter_state",
    "current_company_cohort",
    "filter_state_from_definition",
    "narrow_queryset_to_current_company_filters",
    "load_company_attribute_filter_attributes",
    "parse_company_attribute_filters",
    "resolve_company_cohort",
    "resolve_company_cohorts",
    "resolve_matching_company_ids",
    "serialize_company_attribute_filter_metadata",
    "serialize_company_attribute_filter_state",
]
