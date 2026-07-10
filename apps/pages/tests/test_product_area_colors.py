from django.test import SimpleTestCase

from apps.pages.product_area_colors import (
    build_product_area_color_lookup,
    product_area_color_from_lookup,
    resolve_product_area_colors,
)


class ProductAreaColorsTests(SimpleTestCase):
    def test_resolves_missing_colors_from_visits_palette_order(self):
        areas = resolve_product_area_colors([
            {'key': 'project-management', 'name': 'Project management', 'color': ''},
            {'key': 'core-workspace', 'name': 'Core workspace', 'color': ''},
        ])

        self.assertEqual(areas[0]['color'], '#4269D0')
        self.assertEqual(areas[1]['color'], '#EFB118')

    def test_visits_palette_is_default_even_when_db_color_exists(self):
        areas = resolve_product_area_colors([
            {'key': 'core', 'name': 'Core product', 'color': '#123456'},
            {'key': 'billing', 'name': 'Billing', 'color': ''},
        ])

        self.assertEqual(areas[0]['color'], '#4269D0')
        self.assertEqual(areas[1]['color'], '#EFB118')

    def test_can_preserve_explicit_product_area_color_when_requested(self):
        areas = resolve_product_area_colors(
            [
                {'key': 'core', 'name': 'Core product', 'color': '#123456'},
                {'key': 'billing', 'name': 'Billing', 'color': ''},
            ],
            prefer_explicit=True,
        )

        self.assertEqual(areas[0]['color'], '#123456')
        self.assertEqual(areas[1]['color'], '#EFB118')

    def test_uses_lookup_for_distribution_rows(self):
        areas = resolve_product_area_colors([
            {'key': 'project-management', 'name': 'Project management', 'color': ''},
            {'key': 'core-workspace', 'name': 'Core workspace', 'color': ''},
        ])
        lookup = build_product_area_color_lookup(areas)

        self.assertEqual(
            product_area_color_from_lookup(lookup, {'product_area_key': 'core-workspace'}),
            '#EFB118',
        )
