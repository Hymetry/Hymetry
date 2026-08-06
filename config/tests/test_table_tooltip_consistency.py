import re
from pathlib import Path

from django.test import SimpleTestCase


BASE_DIR = Path(__file__).resolve().parents[2]
TABLE_HEADER_RE = re.compile(r'<th\b[\s\S]*?</th>', re.IGNORECASE)
COLUMN_HEADER_RE = re.compile(
    r'<div\b[^>]*role=["\']columnheader["\'][^>]*>[\s\S]*?</div>',
    re.IGNORECASE,
)
CHANGE_TOOLTIP_RE = re.compile(
    r'<div class="pages-change-delta[^"]*"[^>]*>[\s\S]*?</div>',
    re.IGNORECASE,
)


# The contract explains *metric* columns, whose meaning the reader cannot
# derive from the label alone. The company attributes manager is a settings
# table: its columns are the attribute names the user chose, so there is no
# explanation the application could write for them, and its remaining headers
# are a company link and an edit affordance. Its headers are also sort buttons,
# and no header anywhere else nests a focusable tooltip inside a control.
TOOLTIP_EXEMPT_SOURCES = frozenset({
    'static/js/projects/company-attributes.js',
})


def _application_markup_sources():
    yield from sorted((BASE_DIR / 'apps').rglob('*.html'))
    yield from sorted((BASE_DIR / 'templates').rglob('*.html'))

    for path in sorted((BASE_DIR / 'static' / 'js').rglob('*.js')):
        if path.name.endswith('.min.js') or path.name == 'lib-player.js' or 'vendor' in path.parts:
            continue
        if path.relative_to(BASE_DIR).as_posix() in TOOLTIP_EXEMPT_SOURCES:
            continue
        yield path


class TableTooltipConsistencyTests(SimpleTestCase):
    def test_every_table_column_header_has_an_explanation_tooltip(self):
        for path in _application_markup_sources():
            source = path.read_text(encoding='utf-8')

            for index, header in enumerate(TABLE_HEADER_RE.findall(source), start=1):
                with self.subTest(path=path.relative_to(BASE_DIR), header=index):
                    self.assertTrue(
                        'metric-header-tooltip' in header or 'tableHeaderTooltip(' in header,
                        'Table column header is missing an explanation tooltip.',
                    )
                    if 'tableHeaderTooltip(' not in header:
                        self.assertIn('aria-describedby=', header)
                        self.assertIn('role="tooltip"', header)

            for index, header in enumerate(COLUMN_HEADER_RE.findall(source), start=1):
                with self.subTest(path=path.relative_to(BASE_DIR), column_header=index):
                    self.assertTrue(
                        'metric-header-tooltip' in header or 'tableHeaderTooltip(' in header,
                        'Div-based column header is missing an explanation tooltip.',
                    )

    def test_table_change_values_use_the_standard_period_comparison_tooltip(self):
        blocks_found = 0

        for path in _application_markup_sources():
            if path.suffix != '.js':
                continue

            source = path.read_text(encoding='utf-8')
            change_tooltips = CHANGE_TOOLTIP_RE.findall(source)
            if change_tooltips:
                self.assertIn('label: "Current period"', source)
                self.assertIn('label: "Previous period"', source)
                self.assertIn('label: "Change"', source)

            for index, tooltip in enumerate(change_tooltips, start=1):
                blocks_found += 1
                with self.subTest(path=path.relative_to(BASE_DIR), change=index):
                    self.assertIn('metric-header-tooltip', tooltip)
                    self.assertIn('role="tooltip"', tooltip)

        self.assertGreater(blocks_found, 0)

        for relative_path in (
            Path('static/js/pages/pages-analytics.js'),
        ):
            source = (BASE_DIR / relative_path).read_text(encoding='utf-8')
            self.assertIn('table-change-tooltip metric-header-tooltip', source)
            self.assertIn('label: "Current period"', source)
            self.assertIn('label: "Previous period"', source)
            self.assertIn('label: "Change"', source)

    def test_table_change_tooltips_cover_new_and_missing_comparisons(self):
        change_sources = [
            BASE_DIR / 'static' / 'js' / 'pages' / 'pages-analytics.js',
            BASE_DIR / 'static' / 'js' / 'companies' / 'companies-analytics.js',
            BASE_DIR / 'static' / 'js' / 'companies' / 'company-detail.js',
            BASE_DIR / 'static' / 'js' / 'users' / 'users-analytics.js',
            BASE_DIR / 'static' / 'js' / 'users' / 'user-detail.js',
        ]

        for path in change_sources:
            source = path.read_text(encoding='utf-8')
            with self.subTest(path=path.relative_to(BASE_DIR)):
                self.assertIn('label: "Previous period", value: "No data"', source)
                self.assertIn('"New"', source)

    def test_shared_multi_value_tooltips_use_the_standard_table_markup(self):
        helper = (
            BASE_DIR / 'static' / 'js' / 'shared' / 'analytics-tooltips.js'
        ).read_text(encoding='utf-8')
        css = (BASE_DIR / 'static' / 'css' / 'table-tooltips.css').read_text(encoding='utf-8')

        self.assertIn('analytics-tooltip__row', helper)
        self.assertIn('analytics-tooltip__label', helper)
        self.assertIn('<strong class="analytics-tooltip__value">', helper)
        self.assertRegex(
            css,
            r'\.analytics-tooltip__row\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\) auto;',
        )
        self.assertRegex(
            css,
            r'\.analytics-tooltip__label\s*\{[\s\S]*?text-align:\s*left;',
        )
        self.assertRegex(
            css,
            r'\.analytics-tooltip__value\s*\{[\s\S]*?font-weight:\s*600 !important;[\s\S]*?text-align:\s*right;',
        )

    def test_shared_tooltip_visual_contract_is_14px_dark_gray(self):
        css = (BASE_DIR / 'static' / 'css' / 'table-tooltips.css').read_text(encoding='utf-8')

        self.assertRegex(
            css,
            r'\.metric-header-tooltip__content,[\s\S]*?\[role="tooltip"\]\s*\{[\s\S]*?color:\s*var\(--color-slate-700, #334155\) !important;[\s\S]*?font-size:\s*14px !important;',
        )
        self.assertRegex(
            css,
            r'#vg-tooltip-element\s*\{[\s\S]*?color:\s*var\(--color-slate-700, #334155\) !important;[\s\S]*?font-size:\s*14px !important;',
        )
        self.assertRegex(
            css,
            r'#vg-tooltip-element td\.value\s*\{[\s\S]*?font-weight:\s*600 !important;[\s\S]*?text-align:\s*right !important;',
        )
        self.assertRegex(
            css,
            r'#vg-tooltip-element td\.key\s*\{[\s\S]*?max-width:\s*none !important;[\s\S]*?text-align:\s*left !important;[\s\S]*?white-space:\s*nowrap;',
        )

    def test_overview_sparklines_keep_their_area_visible_while_showing_tooltips(self):
        chart_blocks = (
            (
                'Pages KPI',
                BASE_DIR / 'static' / 'js' / 'pages' / 'pages-analytics.js',
                'function createKpiTrendOption',
                'function mountKpiTrendCharts',
            ),
            (
                'Product area summary',
                BASE_DIR / 'static' / 'js' / 'pages' / 'pages-analytics.js',
                'function createProductAreaTrendOption',
                'function registerProductAreaTrendPayload',
            ),
            (
                'Companies KPI',
                BASE_DIR / 'static' / 'js' / 'companies' / 'companies-analytics.js',
                'function createKpiTrendOption',
                'function createHealthDistributionOption',
            ),
            (
                'Users KPI',
                BASE_DIR / 'static' / 'js' / 'users' / 'users-analytics.js',
                'function createKpiTrendOption',
                'function renderInsights',
            ),
        )

        for name, path, start_marker, end_marker in chart_blocks:
            source = path.read_text(encoding='utf-8')
            chart_option = source[
                source.index(start_marker):
                source.index(end_marker, source.index(start_marker))
            ]

            with self.subTest(chart=name):
                self.assertIn('appendTo: "body"', chart_option)
                self.assertIn('confine: false', chart_option)
                self.assertNotIn('confine: true', chart_option)
                self.assertRegex(
                    chart_option,
                    r'emphasis:\s*\{\s*disabled:\s*true\s*\}',
                )

    def test_company_engagement_tooltips_share_core_fields_and_keep_company_context(self):
        pages_source = (
            BASE_DIR / 'static' / 'js' / 'pages' / 'pages-analytics.js'
        ).read_text(encoding='utf-8')
        companies_source = (
            BASE_DIR / 'static' / 'js' / 'companies' / 'companies-analytics.js'
        ).read_text(encoding='utf-8')
        metric_fields = [
            "'Avg active users'",
            "'Avg engaged time / user'",
            "'Total engaged time'",
            "'Visits'",
        ]

        pages_signal = next(
            line for line in pages_source.splitlines()
            if "{'title': datum.company_name" in line
        )
        companies_signal = next(
            line for line in companies_source.splitlines()
            if "{'title': datum.companyName" in line
        )
        self.assertEqual(metric_fields, sorted(metric_fields, key=pages_signal.index))
        self.assertEqual(metric_fields, sorted(metric_fields, key=companies_signal.index))
        self.assertNotIn("'Company'", pages_signal)
        self.assertNotIn("'Company'", companies_signal)

        extra_fields = ["'Status'", "'Product areas used'", "'Last seen'"]
        for field in extra_fields:
            self.assertIn(field, companies_signal)
        self.assertLess(companies_signal.index(metric_fields[-1]), companies_signal.index(extra_fields[0]))

        pages_scatter_spec = pages_source[
            pages_source.index('function createCompanyEngagementScatterSpec'):
            pages_source.index('function mountCompanyEngagementScatterChart')
        ]
        companies_scatter_spec = companies_source[
            companies_source.index('function createCompanyEngagementScatterSpec'):
            companies_source.index('function mountCompanyEngagementScatter')
        ]
        self.assertIn('cursor: { value: "default" }', pages_scatter_spec)
        self.assertIn('cursor: { value: "default" }', companies_scatter_spec)
        self.assertNotIn('cursor: { value: "pointer" }', pages_scatter_spec)

    def test_user_status_mix_tooltip_uses_three_aligned_data_columns(self):
        """
        The two-bar status mix reports its count and share as separate rows.

        It replaced a stacked-area timeline, and it now shares the Company health
        distribution's treatment, so it reads the same way: one labelled row per
        value rather than a count crammed into the share string.
        """

        users_source = (
            BASE_DIR / 'static' / 'js' / 'users' / 'users-analytics.js'
        ).read_text(encoding='utf-8')
        status_mix = users_source[
            users_source.index('function createStatusMixComparisonOption'):
            users_source.index('function createEngagementBucketBarOption')
        ]
        companies_source = (
            BASE_DIR / 'static' / 'js' / 'companies' / 'companies-analytics.js'
        ).read_text(encoding='utf-8')
        health_distribution = companies_source[
            companies_source.index('function createHealthDistributionEchartsOption'):
            companies_source.index('function renderHealthDistributionEcharts')
        ]

        self.assertIn('{ label: "Users", value: formatNumber(item.count || 0)', status_mix)
        self.assertIn('{ label: "Share", value: item.pctLabel || "0%" }', status_mix)
        self.assertNotIn(' · ', status_mix)
        self.assertNotIn('secondaryValue', status_mix)
        # The component it borrows from labels its own rows the same way.
        self.assertIn('{ label: "Share", value: item.pctLabel || "0%" }', health_distribution)

    def test_user_consistency_labels_follow_company_engagement_map_pattern(self):
        users_source = (
            BASE_DIR / 'static' / 'js' / 'users' / 'users-analytics.js'
        ).read_text(encoding='utf-8')
        scatter_spec = users_source[
            users_source.index('function createUserConsistencyScatterSpec'):
            users_source.index('function userQuadrantText')
        ]
        companies_source = (
            BASE_DIR / 'static' / 'js' / 'companies' / 'companies-analytics.js'
        ).read_text(encoding='utf-8')
        companies_scatter = companies_source[
            companies_source.index('function createCompanyEngagementScatterSpec'):
            companies_source.index('function quadrantText')
        ]

        self.assertNotIn('name: "labelPoints"', scatter_spec)
        self.assertIn('from: { data: "userPoints" }', scatter_spec)
        self.assertIn("text: { signal: \"datum.datum.showLabel ? datum.datum.userName : ''\" }", scatter_spec)
        self.assertIn('opacity: { signal: "datum.datum.showLabel ? 1 : 0" }', scatter_spec)
        self.assertNotIn('avoidMarks:', scatter_spec)
        self.assertIn('offset: [3]', scatter_spec)
        self.assertIn('size: { signal: "datum.pointSize * 1.18" }', scatter_spec)
        self.assertIn('from: { data: "companyPoints" }', companies_scatter)
        self.assertIn('text: { field: "datum.companyName" }', companies_scatter)
        self.assertNotIn('avoidMarks:', companies_scatter)
        self.assertIn('offset: [3]', companies_scatter)

    def test_user_consistency_tooltip_has_user_and_area_usage_sections(self):
        users_source = (
            BASE_DIR / 'static' / 'js' / 'users' / 'users-analytics.js'
        ).read_text(encoding='utf-8')
        scatter_spec = users_source[
            users_source.index('function createUserConsistencyScatterSpec'):
            users_source.index('function userQuadrantText')
        ]
        formatter = users_source[
            users_source.index('function formatUserConsistencyTooltip'):
            users_source.index('function mountConsistencyIntensityScatter')
        ]

        self.assertIn('signal: "datum"', scatter_spec)
        self.assertIn('title: value.userName || "User"', formatter)
        self.assertIn('title: "Area usage"', formatter)
        self.assertIn('{ label: "Company", value:', formatter)
        self.assertIn('{ label: "Avg engaged/session", value:', formatter)
        self.assertIn('rows: areaRows', formatter)
        self.assertIn('formatTooltip: formatUserConsistencyTooltip', users_source)

    def test_user_consistency_scatter_is_independent_from_table_page_loading(self):
        users_source = (
            BASE_DIR / 'static' / 'js' / 'users' / 'users-analytics.js'
        ).read_text(encoding='utf-8')
        filtered_users = users_source[
            users_source.index('function getConsistencyFilteredUsers'):
            users_source.index('function areaUsageSegments')
        ]
        table_loader = users_source[
            users_source.index('function loadUsersTablePage'):
            users_source.index('function simulateUsersTableLoad')
        ]

        self.assertLess(filtered_users.index('data.scatter'), filtered_users.index('data.users'))
        self.assertIn('provider.loadUsersTable', table_loader)
        self.assertNotIn('mountConsistencyIntensityScatter', table_loader)
        self.assertNotIn('hydrateDeferredUsersData', users_source)
        self.assertNotIn('loadDeferredUsersData', users_source)

    def test_analytics_data_hints_do_not_fall_back_to_native_title_tooltips(self):
        paths = [
            BASE_DIR / 'static' / 'js' / 'companies' / 'companies-analytics.js',
            BASE_DIR / 'static' / 'js' / 'companies' / 'company-detail.js',
            BASE_DIR / 'static' / 'js' / 'users' / 'users-analytics.js',
            BASE_DIR / 'static' / 'js' / 'users' / 'user-detail.js',
            BASE_DIR / 'static' / 'js' / 'tracker' / 'visits-charts.js',
            BASE_DIR / 'static' / 'js' / 'tracker' / 'replay-timeline.js',
            BASE_DIR / 'apps' / 'tracker' / 'templates' / 'tracker' / 'recording.html',
        ]

        for path in paths:
            source = path.read_text(encoding='utf-8')
            with self.subTest(path=path.relative_to(BASE_DIR)):
                self.assertNotRegex(source, r'(?<![-\w])title=["\']')
                self.assertNotIn('setAttribute("title"', source)
                if path.name == 'recording.html':
                    self.assertNotRegex(source, r'\bel\.title\s*=')

        pages_template = (
            BASE_DIR / 'apps' / 'pages' / 'templates' / 'pages' / 'overview.html'
        ).read_text(encoding='utf-8')
        pages_source = (
            BASE_DIR / 'static' / 'js' / 'pages' / 'pages-analytics.js'
        ).read_text(encoding='utf-8')
        self.assertIn('title="{% if pages_product_area_filter_has_selection %}', pages_template)
        self.assertIn('label.title = displayLabel', pages_source)
        self.assertIn('title="${escapeHtml(`${metric.label}: daily ${metricConfig.deltaUnit} change vs previous period`)}"', pages_source)
        self.assertIn('class="two-way-movement__pair" title="${escapeHtml(pair)}"', pages_source)

    def test_only_interactive_table_headers_use_the_pointer_cursor(self):
        css = (BASE_DIR / 'static' / 'css' / 'table-tooltips.css').read_text(encoding='utf-8')

        self.assertRegex(
            css,
            r'thead \.metric-header-tooltip,[\s\S]*?\[role="columnheader"\] \.metric-header-tooltip,[\s\S]*?cursor: default;',
        )
        self.assertRegex(
            css,
            r'thead \.metric-header-tooltip > button:not\(:disabled\),[\s\S]*?\[role="columnheader"\] \.metric-header-tooltip > a\[href\][\s\S]*?cursor: pointer;',
        )

        company_detail = (
            BASE_DIR / 'apps' / 'projects' / 'templates' / 'projects' / 'company_detail.html'
        ).read_text(encoding='utf-8')
        areas_used_header = next(
            header
            for header in TABLE_HEADER_RE.findall(company_detail)
            if 'company-users-tooltip-area-usage' in header
        )
        self.assertNotIn('data-user-sort=', areas_used_header)

    def test_base_template_loads_shared_table_tooltip_styles(self):
        base_template = (BASE_DIR / 'templates' / 'base.html').read_text(encoding='utf-8')

        self.assertIn("{% static 'css/table-tooltips.css' %}", base_template)
        self.assertIn("{% static 'js/shared/analytics-tooltips.js' %}", base_template)
