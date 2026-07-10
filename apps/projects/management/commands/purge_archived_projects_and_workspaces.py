from django.core.management.base import BaseCommand

from apps.projects.services import purge_archived_entities


class Command(BaseCommand):
    help = 'Permanently delete archived projects and workspaces whose retention window has expired.'

    def handle(self, *args, **options):
        result = purge_archived_entities()
        self.stdout.write(
            self.style.SUCCESS(
                f"Purged {result['projects']} archived project(s) and {result['workspaces']} archived workspace(s)."
            )
        )
