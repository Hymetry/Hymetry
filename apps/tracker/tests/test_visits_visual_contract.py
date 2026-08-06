import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


def _normalize_css_token(value):
    return ' '.join(value.strip().split())


def _strip_css_comments(value):
    return re.sub(r'/\*.*?\*/', '', value, flags=re.DOTALL)


def _css_blocks(value):
    """Yield top-level ``(prelude, body)`` pairs from a CSS fragment."""
    position = 0
    length = len(value)
    while position < length:
        opening = value.find('{', position)
        if opening < 0:
            return
        prelude = value[position:opening].strip()
        depth = 1
        quote = None
        escaped = False
        closing = opening + 1
        while closing < length and depth:
            character = value[closing]
            if quote:
                if escaped:
                    escaped = False
                elif character == '\\':
                    escaped = True
                elif character == quote:
                    quote = None
            elif character in {'"', "'"}:
                quote = character
            elif character == '{':
                depth += 1
            elif character == '}':
                depth -= 1
            closing += 1
        if depth:
            raise AssertionError(f'Unclosed CSS block after {prelude!r}')
        yield prelude, value[opening + 1:closing - 1]
        position = closing


def _parse_declarations(value):
    declarations = {}
    for declaration in value.split(';'):
        if ':' not in declaration:
            continue
        name, raw_value = declaration.split(':', 1)
        declarations[name.strip()] = _normalize_css_token(raw_value)
    return declarations


def _box_sides(declarations, property_name):
    values = declarations.get(property_name, '').split()
    if len(values) == 1:
        top = right = bottom = left = values[0]
    elif len(values) == 2:
        top = bottom = values[0]
        right = left = values[1]
    elif len(values) == 3:
        top, right, bottom = values
        left = right
    elif len(values) == 4:
        top, right, bottom, left = values
    else:
        top = right = bottom = left = None
    sides = {'top': top, 'right': right, 'bottom': bottom, 'left': left}
    for side in sides:
        sides[side] = declarations.get(f'{property_name}-{side}', sides[side])
    return sides


def _css_rules(value, contexts=()):
    rules = []
    for prelude, body in _css_blocks(value):
        normalized_prelude = _normalize_css_token(prelude)
        if normalized_prelude.startswith('@'):
            rules.extend(_css_rules(body, contexts + (normalized_prelude,)))
            continue
        declarations = _parse_declarations(body)
        for selector in normalized_prelude.split(','):
            rules.append(
                {
                    'contexts': contexts,
                    'selector': selector.strip(),
                    'declarations': declarations,
                }
            )
    return rules


class VisitsVisualCssContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        css_path = Path(settings.BASE_DIR) / 'static/css/tracker/visits.css'
        cls.css = _strip_css_comments(css_path.read_text(encoding='utf-8'))
        cls.rules = _css_rules(cls.css)

    def _rule(self, selector, *contexts):
        normalized_contexts = tuple(_normalize_css_token(value) for value in contexts)
        matches = [
            rule
            for rule in self.rules
            if rule['selector'] == selector and rule['contexts'] == normalized_contexts
        ]
        self.assertTrue(
            matches,
            f'Expected a {selector!r} rule in {normalized_contexts!r}',
        )
        declarations = {}
        for match in matches:
            declarations.update(match['declarations'])
        return declarations

    def assertCssDeclarations(self, selector, expected, *contexts):
        declarations = self._rule(selector, *contexts)
        for property_name, expected_value in expected.items():
            self.assertEqual(
                declarations.get(property_name),
                expected_value,
                f'{selector} / {property_name}',
            )

    def assertCssBox(self, selector, property_name, expected, *contexts):
        actual = _box_sides(self._rule(selector, *contexts), property_name)
        self.assertEqual(actual, expected, f'{selector} / {property_name}')

    def test_body_header_and_layout_match_shared_page_geometry(self):
        body = self._rule('body[data-visits-view="table"]')
        self.assertEqual(
            body.get('background'),
            'var(--color-slate-50, #f8fafc)',
        )
        self.assertEqual(self._rule('html').get('scrollbar-gutter'), 'stable')

        self.assertCssDeclarations(
            '.visits-page-header',
            {'margin': '0 0 2rem'},
        )
        self.assertCssBox(
            '.visits-page-header',
            'padding',
            {'top': '0', 'right': '0', 'bottom': '0', 'left': '0'},
        )
        self.assertCssDeclarations(
            '.visits-page-header__content',
            {
                'display': 'flex',
                'flex-wrap': 'wrap',
                'align-items': 'flex-end',
                'justify-content': 'space-between',
                'gap': '1rem',
            },
        )
        self.assertCssDeclarations(
            '.visits-page-header__intro',
            {
                'min-width': 'max-content',
                'flex': '1 1 0',
            },
        )
        self.assertCssDeclarations(
            '.visits-filter-bar',
            {
                'position': 'relative',
                'z-index': '9',
                'max-width': '100%',
                'flex': '0 0 auto',
                'flex-wrap': 'nowrap',
                'margin': '0 0 0 auto',
            },
        )
        self.assertCssDeclarations(
            '.visits-layout',
            {
                'position': 'relative',
                'display': 'flex',
                'align-items': 'flex-start',
                'margin': '0',
                'padding-top': '1rem',
                'container-name': 'visits-table',
                'container-type': 'inline-size',
                'overflow-x': 'auto',
                'overflow-y': 'visible',
            },
        )

    def test_visits_dropdown_filters_match_reference_geometry(self):
        self.assertCssDeclarations(
            '.visits-filter--entity',
            {'width': 'clamp(12.5rem, 16vw, 15rem)'},
        )
        self.assertCssDeclarations(
            '.visits-filter--page',
            {'width': 'clamp(12.5rem, 16vw, 15rem)'},
        )
        self.assertCssDeclarations(
            '.visits-filter__button',
            {
                'display': 'flex',
                'width': '100%',
                'height': '2.25rem',
                'border-radius': '0.375rem',
                'padding': '0 2.25rem 0 0.75rem',
                'text-align': 'left',
            },
        )
        self.assertCssDeclarations(
            '.visits-filter--entity .visits-filter__popover',
            {'width': '24rem'},
        )
        self.assertCssDeclarations(
            '.visits-filter--page .visits-filter__popover',
            {
                'right': '0',
                'left': 'auto',
                'width': '23rem',
            },
        )
        self.assertCssDeclarations(
            '.visits-filter__options',
            {
                'max-height': '18rem',
                'overflow-y': 'auto',
                'padding': '0.375rem',
            },
        )
        self.assertCssDeclarations(
            '.visits-filter__search',
            {
                'width': '100%',
                'height': '2.25rem',
                'border-radius': '0.375rem',
                'padding': '0 0.75rem',
            },
        )

    def test_visits_dropdown_filters_match_reference_colors(self):
        self.assertCssDeclarations(
            '.visits-filter__button',
            {
                'border': '1px solid var(--color-slate-200, #e2e8f0)',
                'background': 'var(--color-white, #fff)',
                'color': 'var(--color-slate-700, #334155)',
            },
        )
        self.assertCssDeclarations(
            '.visits-filter__button[aria-expanded="true"]',
            {
                'border-color': 'var(--color-blue-400, #60a5fa)',
                'box-shadow': (
                    '0 0 0 3px color-mix(in oklab, '
                    'var(--color-blue-400, #60a5fa) 18%, transparent)'
                ),
            },
        )
        self.assertCssDeclarations(
            '.visits-filter__button[data-has-selection="true"]',
            {
                'border-color': 'var(--color-sky-300, #7dd3fc)',
                'background': 'var(--color-sky-50, #f0f9ff)',
                'color': 'var(--color-sky-900, #0c4a6e)',
            },
        )
        self.assertCssDeclarations(
            '.visits-filter__search:focus',
            {
                'border-color': 'var(--color-blue-400, #60a5fa)',
                'box-shadow': (
                    '0 0 0 3px color-mix(in oklab, '
                    'var(--color-blue-400, #60a5fa) 18%, transparent)'
                ),
            },
        )
        self.assertCssDeclarations(
            '.visits-filter__option[aria-selected="true"]',
            {'background': 'var(--color-sky-50, #f0f9ff)'},
        )
        self.assertCssDeclarations(
            '.visits-filter__option[aria-selected="true"]::after',
            {'color': 'var(--color-sky-700, #0369a1)'},
        )

    def test_table_columns_rows_and_chart_keep_reference_dimensions(self):
        self.assertCssDeclarations(
            '.visits-table-shell',
            {
                '--visits-session-meta-width': '36.25rem',
                '--visits-session-grid-columns': '7rem 6rem 8.75rem 4.5rem 7rem',
                '--visits-major-tick-width': '100px',
                'width': '100%',
                'min-width': 'calc(var(--visits-session-meta-width) + 518px)',
            },
        )
        self.assertNotIn(
            'min-height',
            self._rule('.visits-table-shell'),
        )
        self.assertCssDeclarations(
            '.visits-table-shell--with-play',
            {
                '--visits-play-column-width': '2.5rem',
                '--visits-session-data-width': '36.25rem',
                '--visits-session-data-grid-columns': '7rem 6rem 8.75rem 4.5rem 7rem',
                '--visits-session-meta-width': (
                    'calc(var(--visits-play-column-width) + 0.75rem + '
                    'var(--visits-session-data-width))'
                ),
                '--visits-session-grid-columns': (
                    'var(--visits-play-column-width) '
                    'var(--visits-session-data-grid-columns)'
                ),
            },
        )
        for selector in ('.visits-session-meta', '.visits-session-header'):
            self.assertCssDeclarations(
                selector,
                {
                    'width': 'var(--visits-session-meta-width)',
                    'flex': '0 0 var(--visits-session-meta-width)',
                    'grid-template-columns': 'var(--visits-session-grid-columns)',
                    'column-gap': '0.75rem',
                },
            )
        self.assertCssDeclarations(
            '.visits-session-header',
            {
                'padding-top': '0.5rem',
                'padding-bottom': '0.5rem',
            },
        )
        self.assertCssDeclarations(
            '.visits-stacked-chart-container',
            {
                'min-width': '502px',
                'min-height': '44px',
                'padding': '0.5rem 0 0.5rem 22px',
            },
        )
        self.assertCssDeclarations(
            '.visits-chart-header',
            {'min-width': '502px'},
        )
        self.assertCssBox(
            '.visits-chart-header',
            'padding',
            {'top': '0.5rem', 'right': '0', 'bottom': '0.5rem', 'left': '22px'},
        )
        self.assertCssDeclarations(
            '.visits-stacked-chart',
            {'height': '28px'},
        )
        self.assertCssDeclarations(
            '[data-visits-session-list]::before',
            {
                'right': '0',
                'left': 'calc(1rem + var(--visits-session-meta-width) + 22px)',
            },
        )

    def test_timeline_zero_line_stays_continuous_across_chart_rows(self):
        self.assertCssDeclarations(
            '[data-visits-session-list]::after',
            {
                'position': 'absolute',
                'z-index': '2',
                'top': '0',
                'bottom': '0',
                'left': 'calc(1rem + var(--visits-session-meta-width) + 22px)',
                'width': '1px',
                'background': '#eceef2',
                'content': '""',
                'pointer-events': 'none',
            },
        )

    def test_native_row_link_keeps_entity_links_aligned_and_interactive(self):
        for selector in ('.visits-session-link', '.visits-session-link *'):
            self.assertCssDeclarations(
                selector,
                {'cursor': 'pointer !important'},
            )

        self.assertCssDeclarations(
            '.visits-session-link .visits-session-meta > span:nth-child(-n + 2)',
            {'visibility': 'hidden'},
        )
        self.assertCssDeclarations(
            '.visits-table-shell--with-play .visits-session-link .visits-session-meta > span:nth-child(3)',
            {'visibility': 'hidden'},
        )
        self.assertCssDeclarations(
            '.visits-play-button',
            {
                'position': 'absolute',
                'z-index': '6',
                'top': '0.3125rem',
                'left': '0.5625rem',
                'width': '1.875rem',
                'height': '1.875rem',
                'opacity': '0.62',
            },
        )
        self.assertCssDeclarations(
            '[data-visits-session-list] > li:hover .visits-play-button',
            {
                'color': 'var(--color-slate-700, #334155)',
                'opacity': '1',
            },
        )
        self.assertCssDeclarations(
            '[data-visits-session-list] > li:hover .visits-play-button:hover',
            {
                'background': 'var(--color-green-50, #f0fdf4)',
                'color': 'var(--color-green-700, #15803d)',
            },
        )
        self.assertCssDeclarations(
            '.visits-session-entity-links',
            {
                'position': 'absolute',
                'z-index': '5',
                'top': '0.625rem',
                'left': '1rem',
                'display': 'grid',
                'width': 'var(--visits-session-meta-width)',
                'grid-template-columns': 'var(--visits-session-grid-columns)',
                'column-gap': '0.75rem',
                'font-weight': '500',
                'pointer-events': 'none',
                'white-space': 'nowrap',
            },
        )
        self.assertCssDeclarations(
            '.visits-table-shell--with-play .visits-session-entity-links',
            {
                'left': 'calc(0.25rem + var(--visits-play-column-width) + 0.75rem)',
                'width': 'var(--visits-session-data-width)',
                'grid-template-columns': 'var(--visits-session-data-grid-columns)',
            },
        )
        for selector in (
            '.visits-session-entity-links > a',
            '.visits-session-entity-links > span',
        ):
            self.assertCssDeclarations(
                selector,
                {
                    'min-width': '0',
                    'max-width': '100%',
                    'justify-self': 'start',
                },
            )
        self.assertCssDeclarations(
            '.visits-session-entity-links > a',
            {
                'cursor': 'pointer',
                'display': 'inline-block',
                'pointer-events': 'auto',
            },
        )
        for selector in (
            '.visits-session-entity-links > a:hover',
            '.visits-session-entity-links > a:focus-visible',
        ):
            self.assertCssDeclarations(
                selector,
                {
                    'background': '#e0f2fe',
                    'color': '#0c4a6e',
                    'text-decoration': 'underline',
                    'text-underline-offset': '0.125rem',
                },
            )

    def test_play_column_reduces_the_internal_leading_gutter(self):
        self.assertCssDeclarations(
            '.visits-table-shell--with-play .visits-session-header',
            {'margin-left': '0.25rem'},
        )
        self.assertCssDeclarations(
            '.visits-table-shell--with-play .visits-session-meta',
            {'margin-left': '0.25rem'},
        )
        self.assertCssDeclarations(
            '.visits-play-button',
            {'left': '0.5625rem'},
        )
        self.assertCssDeclarations(
            '.visits-table-shell--with-play .visits-session-entity-links',
            {'left': 'calc(0.25rem + var(--visits-play-column-width) + 0.75rem)'},
        )
        for selector in (
            '.visits-table-shell--with-play [data-visits-session-list]::before',
            '.visits-table-shell--with-play [data-visits-session-list]::after',
        ):
            self.assertCssDeclarations(
                selector,
                {'left': 'calc(0.25rem + var(--visits-session-meta-width) + 22px)'},
            )

    def test_reference_container_breakpoints_do_not_drift(self):
        self.assertCssDeclarations(
            '.visits-table-shell',
            {
                '--visits-session-meta-width': '38.75rem',
                '--visits-session-grid-columns': '8.5rem 7rem 8.75rem 4.5rem 7rem',
            },
            '@container visits-table (min-width: 1280px)',
        )
        self.assertCssDeclarations(
            '.visits-table-shell--with-play',
            {
                '--visits-session-data-width': '38.75rem',
                '--visits-session-data-grid-columns': '8.5rem 7rem 8.75rem 4.5rem 7rem',
            },
            '@container visits-table (min-width: 1280px)',
        )
        self.assertCssDeclarations(
            '.visits-table-shell',
            {
                '--visits-session-meta-width': '41.25rem',
                '--visits-session-grid-columns': '10rem 8rem 8.75rem 4.5rem 7rem',
            },
            '@container visits-table (min-width: 1600px)',
        )
        self.assertCssDeclarations(
            '.visits-table-shell--with-play',
            {
                '--visits-session-data-width': '41.25rem',
                '--visits-session-data-grid-columns': '10rem 8rem 8.75rem 4.5rem 7rem',
            },
            '@container visits-table (min-width: 1600px)',
        )
