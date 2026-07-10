from django.core.management.base import BaseCommand

from apps.pages import queries


class Command(BaseCommand):
    help = 'Inspect prepared Pages analytics state for a project.'

    def add_arguments(self, parser):
        parser.add_argument('--project-id', type=int, required=True)

    def handle(self, *args, **options):
        project_id = options['project_id']
        rows = queries.fetch_all(
            """
            SELECT 'product_areas' AS name, COUNT(*) AS count FROM pages_productarea WHERE project_id = %s
            UNION ALL
            SELECT 'page_visits', COUNT(*) FROM pages_pagevisit WHERE project_id = %s
            UNION ALL
            SELECT 'page_transitions', COUNT(*) FROM pages_pagetransition WHERE project_id = %s
            UNION ALL
            SELECT 'page_daily_metrics', COUNT(*) FROM pages_pagedailymetric WHERE project_id = %s
            UNION ALL
            SELECT 'overview_caches', COUNT(*) FROM pages_pagesoverviewcache WHERE project_id = %s
            """,
            [project_id, project_id, project_id, project_id, project_id],
        )
        for row in rows:
            self.stdout.write(f"{row['name']}: {row['count']}")
