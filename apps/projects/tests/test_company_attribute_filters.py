from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse

from apps.pages import services as pages_services
from apps.pages.models import PageVisit
from apps.projects.company_attribute_filters import (
    CompanyAttributeFilterValidationError,
    apply_company_attribute_filters,
    canonical_company_attribute_query_if_needed,
    canonicalize_company_attribute_query,
    company_attribute_filter_scope,
    current_company_attribute_filter_state,
    parse_company_attribute_filters,
    resolve_company_cohort,
    resolve_matching_company_ids,
    serialize_company_attribute_filter_state,
)
from apps.projects.models import (
    CompanyAttribute,
    CompanyAttributeBooleanDisplay,
    CompanyAttributeMoneyCurrency,
    CompanyAttributeMoneyDisplay,
    CompanyAttributeNumberFormat,
    CompanyAttributeOption,
    CompanyAttributeType,
    CompanyAttributeValue,
    Project,
    Workspace,
    WorkspaceMemberRole,
    WorkspaceMemberStatus,
    WorkspaceMembership,
)


class CompanyAttributeFilterTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="attribute-filter-owner",
            email="attribute-filter-owner@example.com",
            password="testpass123",
        )
        workspace = Workspace.objects.create(
            name="Attribute Filter Workspace",
            website_url="example.com",
            created_by=user,
        )
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=user,
            role=WorkspaceMemberRole.OWNER,
            status=WorkspaceMemberStatus.ACTIVE,
        )
        self.project = Project.objects.create(
            workspace=workspace,
            name="Attribute Filter Project",
            created_by=user,
        )
        self.user = user
        self.client.force_login(user)
        self.other_project = Project.objects.create(
            workspace=workspace,
            name="Other Attribute Filter Project",
            created_by=user,
        )

        self.text = CompanyAttribute.objects.create(
            project=self.project,
            name="Notes",
            attribute_type=CompanyAttributeType.TEXT,
            position=0,
        )
        self.number = CompanyAttribute.objects.create(
            project=self.project,
            name="Employees",
            attribute_type=CompanyAttributeType.NUMBER,
            number_format=CompanyAttributeNumberFormat.PLAIN,
            decimal_places=2,
            position=1,
        )
        self.money = CompanyAttribute.objects.create(
            project=self.project,
            name="ARR",
            attribute_type=CompanyAttributeType.MONEY,
            currency=CompanyAttributeMoneyCurrency.USD,
            money_display=CompanyAttributeMoneyDisplay.COMPACT,
            position=2,
        )
        self.date = CompanyAttribute.objects.create(
            project=self.project,
            name="Renewal",
            attribute_type=CompanyAttributeType.DATE,
            position=3,
        )
        self.boolean = CompanyAttribute.objects.create(
            project=self.project,
            name="Strategic",
            attribute_type=CompanyAttributeType.BOOLEAN,
            boolean_display=CompanyAttributeBooleanDisplay.YES_NO,
            position=4,
        )
        self.select = CompanyAttribute.objects.create(
            project=self.project,
            name="Plan",
            attribute_type=CompanyAttributeType.SINGLE_SELECT,
            position=5,
        )
        self.free = CompanyAttributeOption.objects.create(
            attribute=self.select,
            label="Free",
            position=0,
        )
        self.pro = CompanyAttributeOption.objects.create(
            attribute=self.select,
            label="Pro",
            position=1,
        )
        self.enterprise = CompanyAttributeOption.objects.create(
            attribute=self.select,
            label="Enterprise",
            position=2,
        )

        self.other_text = CompanyAttribute.objects.create(
            project=self.other_project,
            name="Notes",
            attribute_type=CompanyAttributeType.TEXT,
        )
        self.other_select = CompanyAttribute.objects.create(
            project=self.other_project,
            name="Plan",
            attribute_type=CompanyAttributeType.SINGLE_SELECT,
            position=1,
        )
        self.other_option = CompanyAttributeOption.objects.create(
            attribute=self.other_select,
            label="Other project",
        )

        for company_id in ("acme", "beta", "gamma", "blank", "missing"):
            self._visit(company_id)
        self._visit(None)
        self._visit("")

        self._value(self.text, "acme", text_value="Alpha Customer")
        self._value(self.text, "beta", text_value="Beta")
        self._value(self.text, "gamma", text_value="Gamma")
        # Storage permits an empty text row even though normal writes clear it.
        CompanyAttributeValue.objects.bulk_create(
            [CompanyAttributeValue(attribute=self.text, company_id="blank", text_value="")]
        )
        for company_id, value in (("acme", "10"), ("beta", "20"), ("gamma", "30")):
            self._value(self.number, company_id, decimal_value=Decimal(value))
        for company_id, value in (
            ("acme", "0.1"),
            ("beta", "0.3"),
            ("gamma", "0.3000000001"),
        ):
            self._value(self.money, company_id, decimal_value=Decimal(value))
        for company_id, value in (
            ("acme", date(2026, 7, 10)),
            ("beta", date(2026, 7, 20)),
            ("gamma", date(2026, 7, 31)),
        ):
            self._value(self.date, company_id, date_value=value)
        self._value(self.boolean, "acme", boolean_value=True)
        self._value(self.boolean, "beta", boolean_value=False)
        self._value(self.boolean, "gamma", boolean_value=True)
        self._value(self.select, "acme", option=self.pro)
        self._value(self.select, "beta", option=self.free)
        self._value(self.select, "gamma", option=self.enterprise)

        # A same-named definition/value in another project must never qualify.
        self._value(self.other_text, "missing", text_value="Alpha Customer")

    def _visit(self, company_id):
        # Every overview period ends on the last complete project-local day, so
        # a visit stamped "now" falls outside all of them. Placing it inside
        # that last complete day keeps it eligible for every range key.
        _start_date, end_date = pages_services.resolve_period(
            self.project.timezone,
            range_key="last_30_days",
        )
        day_start, _day_end = pages_services._utc_bounds_for_local_dates(
            end_date,
            end_date,
            self.project.timezone,
        )
        visit_start = day_start + timedelta(hours=1)
        return PageVisit.objects.create(
            project=self.project,
            session_id=uuid4(),
            company_id=company_id,
            visit_start_ts=visit_start,
            visit_end_ts=visit_start + timedelta(minutes=1),
        )

    def _value(self, attribute, company_id, **typed_value):
        return CompanyAttributeValue.objects.create(
            attribute=attribute,
            company_id=company_id,
            **typed_value,
        )

    def _query(self, *pairs):
        query = QueryDict("", mutable=True)
        for key, value in pairs:
            query.appendlist(key, str(value))
        return query

    def _state(self, attribute, operator, **fields):
        pairs = [(f"ca.{attribute.id}.op", operator)]
        for field_name, raw_value in fields.items():
            values = raw_value if isinstance(raw_value, (list, tuple)) else [raw_value]
            pairs.extend((f"ca.{attribute.id}.{field_name}", value) for value in values)
        return parse_company_attribute_filters(self.project, self._query(*pairs), strict=True)

    def _company_ids(self, state):
        queryset = PageVisit.objects.filter(project=self.project).order_by("company_id", "id")
        return list(
            apply_company_attribute_filters(queryset, state)
            .values_list("company_id", flat=True)
        )

    def test_select_operators_or_empty_and_not_empty(self):
        state = self._state(self.select, "in", value=[self.enterprise.id, self.pro.id])
        self.assertEqual(self._company_ids(state), ["acme", "gamma"])
        self.assertEqual(state.active_count, 1)
        self.assertEqual(state.summaries, ("Plan: Pro, Enterprise",))

        state = self._state(self.select, "not_in", value=[self.pro.id])
        self.assertEqual(self._company_ids(state), ["beta", "gamma"])
        self.assertEqual(self._company_ids(self._state(self.select, "empty")), ["blank", "missing"])
        self.assertEqual(
            self._company_ids(self._state(self.select, "not_empty")),
            ["acme", "beta", "gamma"],
        )

    def test_every_text_operator_and_blank_storage_semantics(self):
        cases = (
            ("contains", " customer ", ["acme"]),
            ("not_contains", "customer", ["beta", "gamma"]),
            ("eq", " beta ", ["beta"]),
            ("neq", "Beta", ["acme", "gamma"]),
        )
        for operator, value, expected in cases:
            with self.subTest(operator=operator):
                self.assertEqual(
                    self._company_ids(self._state(self.text, operator, value=value)),
                    expected,
                )
        self.assertEqual(self._company_ids(self._state(self.text, "empty")), ["blank", "missing"])
        self.assertEqual(
            self._company_ids(self._state(self.text, "not_empty")),
            ["acme", "beta", "gamma"],
        )

    def test_every_number_operator_and_inclusive_between(self):
        cases = (
            ("eq", "20", ["beta"]),
            ("gt", "20", ["gamma"]),
            ("gte", "20", ["beta", "gamma"]),
            ("lt", "20", ["acme"]),
            ("lte", "20", ["acme", "beta"]),
        )
        for operator, value, expected in cases:
            with self.subTest(operator=operator):
                self.assertEqual(
                    self._company_ids(self._state(self.number, operator, value=value)),
                    expected,
                )
        self.assertEqual(
            self._company_ids(self._state(self.number, "between", min="10", max="20")),
            ["acme", "beta"],
        )
        self.assertEqual(self._company_ids(self._state(self.number, "empty")), ["blank", "missing"])
        self.assertEqual(
            self._company_ids(self._state(self.number, "not_empty")),
            ["acme", "beta", "gamma"],
        )

    def test_money_uses_exact_decimals_and_every_comparison(self):
        cases = (
            ("eq", "0.3", ["beta"]),
            ("gt", "0.3", ["gamma"]),
            ("gte", "0.3", ["beta", "gamma"]),
            ("lt", "0.3", ["acme"]),
            ("lte", "0.3", ["acme", "beta"]),
        )
        for operator, value, expected in cases:
            with self.subTest(operator=operator):
                self.assertEqual(
                    self._company_ids(self._state(self.money, operator, value=value)),
                    expected,
                )
        self.assertEqual(
            self._company_ids(self._state(self.money, "between", min="0.1", max="0.3")),
            ["acme", "beta"],
        )
        self.assertEqual(self._company_ids(self._state(self.money, "empty")), ["blank", "missing"])
        self.assertEqual(
            self._company_ids(self._state(self.money, "not_empty")),
            ["acme", "beta", "gamma"],
        )

    def test_every_date_operator_and_inclusive_between(self):
        cases = (
            ("on", "2026-07-20", ["beta"]),
            ("before", "2026-07-20", ["acme"]),
            ("after", "2026-07-20", ["gamma"]),
        )
        for operator, value, expected in cases:
            with self.subTest(operator=operator):
                self.assertEqual(
                    self._company_ids(self._state(self.date, operator, value=value)),
                    expected,
                )
        self.assertEqual(
            self._company_ids(
                self._state(self.date, "between", **{"from": "2026-07-10", "to": "2026-07-20"})
            ),
            ["acme", "beta"],
        )
        self.assertEqual(self._company_ids(self._state(self.date, "empty")), ["blank", "missing"])
        self.assertEqual(
            self._company_ids(self._state(self.date, "not_empty")),
            ["acme", "beta", "gamma"],
        )

    def test_boolean_yes_and_no(self):
        self.assertEqual(
            self._company_ids(self._state(self.boolean, "eq", value="true")),
            ["acme", "gamma"],
        )
        self.assertEqual(
            self._company_ids(self._state(self.boolean, "eq", value="false")),
            ["beta"],
        )

    def test_and_across_attributes_and_existing_queryset_filters(self):
        query = self._query(
            (f"ca.{self.text.id}.op", "contains"),
            (f"ca.{self.text.id}.value", "customer"),
            (f"ca.{self.boolean.id}.op", "eq"),
            (f"ca.{self.boolean.id}.value", "true"),
        )
        state = parse_company_attribute_filters(self.project, query, strict=True)
        base = PageVisit.objects.filter(project=self.project).exclude(company_id="gamma")
        self.assertEqual(
            list(apply_company_attribute_filters(base, state).values_list("company_id", flat=True)),
            ["acme"],
        )

    def test_negative_filters_exclude_missing_null_blank_and_unknown_identity(self):
        state = self._state(self.text, "neq", value="Beta")
        self.assertEqual(self._company_ids(state), ["acme", "gamma"])
        self.assertNotIn(None, self._company_ids(state))
        self.assertNotIn("", self._company_ids(state))

    def test_empty_only_state_excludes_unidentified_companies(self):
        state = self._state(self.text, "empty")
        self.assertEqual(self._company_ids(state), ["blank", "missing"])

    def test_correlated_exists_does_not_duplicate_outer_rows(self):
        state = self._state(self.select, "in", value=[self.pro.id, self.enterprise.id])
        queryset = PageVisit.objects.filter(project=self.project, company_id="acme")
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(apply_company_attribute_filters(queryset, state).count(), 1)
        self.assertIn("EXISTS", str(apply_company_attribute_filters(queryset, state).query).upper())

    def test_round_trip_canonical_order_hash_and_unrelated_parameters(self):
        query = self._query(
            ("range", "30d"),
            ("area", "one"),
            ("area", "two"),
            ("page", "4"),
            (f"ca.{self.select.id}.value", self.enterprise.id),
            (f"ca.{self.select.id}.op", "in"),
            (f"ca.{self.select.id}.value", self.pro.id),
            (f"ca.{self.money.id}.max", "2.5000"),
            (f"ca.{self.money.id}.op", "between"),
            (f"ca.{self.money.id}.min", "1.00"),
        )
        state = parse_company_attribute_filters(self.project, query, strict=True)
        self.assertEqual(
            state.canonical_pairs,
            (
                (f"ca.{self.money.id}.op", "between"),
                (f"ca.{self.money.id}.min", "1"),
                (f"ca.{self.money.id}.max", "2.5"),
                (f"ca.{self.select.id}.op", "in"),
                (f"ca.{self.select.id}.value", str(self.pro.id)),
                (f"ca.{self.select.id}.value", str(self.enterprise.id)),
            ),
        )
        canonical = canonicalize_company_attribute_query(query, state, reset_page=True)
        self.assertEqual(canonical.getlist("area"), ["one", "two"])
        self.assertEqual(canonical["range"], "30d")
        self.assertNotIn("page", canonical)
        self.assertEqual(
            canonical_company_attribute_query_if_needed(
                query,
                state,
                reset_page=True,
            ),
            canonical,
        )
        self.assertIsNone(
            canonical_company_attribute_query_if_needed(
                canonical,
                state,
                reset_page=True,
            ),
        )
        reparsed = parse_company_attribute_filters(self.project, canonical, strict=True)
        self.assertEqual(reparsed.canonical_pairs, state.canonical_pairs)
        self.assertEqual(reparsed.stable_hash, state.stable_hash)
        self.assertEqual(len(state.stable_hash), 64)

    def test_applied_payload_uses_ids_and_typed_url_fields(self):
        state = parse_company_attribute_filters(
            self.project,
            self._query(
                (f"ca.{self.select.id}.op", "in"),
                (f"ca.{self.select.id}.value", self.pro.id),
                (f"ca.{self.date.id}.op", "between"),
                (f"ca.{self.date.id}.from", "2026-07-01"),
                (f"ca.{self.date.id}.to", "2026-07-31"),
            ),
            strict=True,
        )
        self.assertEqual(
            serialize_company_attribute_filter_state(state),
            {
                str(self.date.id): {
                    "op": "between",
                    "from": "2026-07-01",
                    "to": "2026-07-31",
                },
                str(self.select.id): {"op": "in", "values": [str(self.pro.id)]},
            },
        )

    def test_lenient_parse_omits_malformed_stale_and_cross_project_rows(self):
        query = self._query(
            ("ca.not-an-id.op", "eq"),
            (f"ca.{self.other_text.id}.op", "contains"),
            (f"ca.{self.other_text.id}.value", "Alpha"),
            (f"ca.{self.number.id}.op", "eq"),
            (f"ca.{self.number.id}.value", "not-a-number"),
            (f"ca.{self.select.id}.op", "in"),
            (f"ca.{self.select.id}.value", self.other_option.id),
        )
        state = parse_company_attribute_filters(self.project, query)
        self.assertFalse(state.active)
        self.assertGreaterEqual(len(state.issues), 4)
        self.assertEqual(
            set(self._company_ids(state)),
            {None, "", "acme", "beta", "gamma", "blank", "missing"},
        )
        with self.assertRaises(CompanyAttributeFilterValidationError):
            parse_company_attribute_filters(self.project, query, strict=True)

    def test_lenient_select_keeps_valid_options_while_omitting_stale_ones(self):
        state = parse_company_attribute_filters(
            self.project,
            self._query(
                (f"ca.{self.select.id}.op", "in"),
                (f"ca.{self.select.id}.value", self.pro.id),
                (f"ca.{self.select.id}.value", self.other_option.id),
            ),
        )
        self.assertTrue(state.active)
        self.assertTrue(state.issues)
        self.assertEqual(self._company_ids(state), ["acme"])

    def test_invalid_ranges_duplicates_and_blank_text_are_rejected_strictly(self):
        invalid_queries = (
            self._query(
                (f"ca.{self.number.id}.op", "between"),
                (f"ca.{self.number.id}.min", "20"),
                (f"ca.{self.number.id}.max", "10"),
            ),
            self._query(
                (f"ca.{self.date.id}.op", "between"),
                (f"ca.{self.date.id}.from", "2026-08-01"),
                (f"ca.{self.date.id}.to", "2026-07-01"),
            ),
            self._query(
                (f"ca.{self.text.id}.op", "contains"),
                (f"ca.{self.text.id}.value", " "),
            ),
            self._query(
                (f"ca.{self.boolean.id}.op", "eq"),
                (f"ca.{self.boolean.id}.op", "eq"),
                (f"ca.{self.boolean.id}.value", "true"),
            ),
        )
        for query in invalid_queries:
            with self.subTest(query=query.urlencode()):
                with self.assertRaises(CompanyAttributeFilterValidationError):
                    parse_company_attribute_filters(self.project, query, strict=True)

    def test_context_scope_is_nested_and_restored(self):
        first = self._state(self.text, "contains", value="Alpha")
        second = self._state(self.boolean, "eq", value="true")
        self.assertIsNone(current_company_attribute_filter_state())
        with company_attribute_filter_scope(first):
            self.assertIs(current_company_attribute_filter_state(), first)
            with company_attribute_filter_scope(second):
                self.assertIs(current_company_attribute_filter_state(), second)
            self.assertIs(current_company_attribute_filter_state(), first)
        self.assertIsNone(current_company_attribute_filter_state())

    def test_preview_endpoint_uses_the_same_cohort_and_reports_base_count(self):
        response = self.client.get(
            reverse(
                "projects:project_company_attribute_filter_preview",
                kwargs={"project_id": self.project.id},
            ),
            {
                "surface": "companies",
                f"ca.{self.select.id}.op": "in",
                f"ca.{self.select.id}.value": str(self.pro.id),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "surface": "companies",
                "matching_count": 1,
                "eligible_count": 5,
                "percentage": 20.0,
                "canonicalPairs": [
                    [f"ca.{self.select.id}.op", "in"],
                    [f"ca.{self.select.id}.value", str(self.pro.id)],
                ],
            },
        )

    def _cohort(self, state, observed=("acme", "beta", "gamma", "blank", "missing")):
        return resolve_company_cohort(state, observed)

    def test_cohort_matches_the_queryset_predicates_for_every_operator(self):
        for state in (
            self._state(self.select, "in", value=[self.enterprise.id, self.pro.id]),
            self._state(self.select, "not_in", value=[self.pro.id]),
            self._state(self.select, "not_empty"),
            self._state(self.number, "gte", value="20"),
            self._state(self.boolean, "eq", value="true"),
            self._state(self.text, "contains", value="Alpha"),
        ):
            with self.subTest(summaries=state.summaries):
                self.assertEqual(
                    self._cohort(state),
                    set(self._company_ids(state)),
                )

    def test_an_all_empty_filter_set_resolves_the_companies_without_values(self):
        state = self._state(self.select, "empty")

        # resolve_matching_company_ids anchors on the first non-empty row and so
        # cannot answer this at all; the cohort resolver must.
        self.assertIsNone(resolve_matching_company_ids(state))
        self.assertEqual(self._cohort(state), {"blank", "missing"})

    def test_the_cohort_never_leaves_the_observed_universe(self):
        state = self._state(self.select, "not_empty")

        self.assertEqual(self._cohort(state, observed=("acme",)), {"acme"})
        self.assertEqual(self._cohort(state, observed=()), set())

    def test_blank_observed_identities_are_dropped(self):
        state = self._state(self.select, "empty")

        self.assertEqual(self._cohort(state, observed=("", "   ", "blank")), {"blank"})

    def test_an_inactive_state_has_no_cohort(self):
        state = parse_company_attribute_filters(self.project, self._query())

        self.assertFalse(state.active)
        with self.assertRaises(ValueError):
            resolve_company_cohort(state, ("acme",))
