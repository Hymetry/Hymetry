from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


def _template_files():
    roots = [Path(settings.BASE_DIR) / 'apps', Path(settings.BASE_DIR) / 'templates']
    for root in roots:
        if root.exists():
            yield from sorted(root.rglob('*.html'))


class TemplateCommentSyntaxTests(SimpleTestCase):
    def test_no_template_uses_a_multiline_hash_comment(self):
        """
        `{# #}` is single-line only.

        Django does not treat a `{#` that runs past the end of its line as a
        comment at all: it emits the text verbatim into the page. Inside a loop
        it is emitted once per iteration, so the mistake is loud but only at
        render time. `{% comment %}` is the multi-line form.
        """

        offenders = [
            f'{path.relative_to(settings.BASE_DIR)}:{number}'
            for path in _template_files()
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1)
            if '{#' in line and '#}' not in line
        ]

        self.assertEqual(
            offenders,
            [],
            'Use {% comment %}...{% endcomment %} for comments spanning lines; '
            'a multi-line {# #} renders as visible page text.',
        )
