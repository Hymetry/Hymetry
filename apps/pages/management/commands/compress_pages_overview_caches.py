from django.core.management.base import BaseCommand, CommandError

from apps.pages import services
from apps.pages.models import PagesOverviewCache


class Command(BaseCommand):
    help = (
        "Backfill compressed Pages overview payloads without rebuilding "
        "analytics."
    )

    def add_arguments(self, parser):
        parser.add_argument("--project-id", type=int, required=True)
        parser.add_argument("--range", dest="range_key")
        parser.add_argument("--batch-size", type=int, default=25)
        parser.add_argument(
            "--force",
            action="store_true",
            help="Recompress rows that already have a binary payload.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        if batch_size < 1:
            raise CommandError("--batch-size must be at least 1.")

        caches = PagesOverviewCache.objects.filter(
            project_id=options["project_id"],
        )
        if options.get("range_key"):
            caches = caches.filter(range_key=options["range_key"])
        if not options["force"]:
            caches = caches.filter(payload_compressed__isnull=True)
        caches = caches.only(
            "id",
            "payload_json",
            "generated_at",
        ).order_by("id")

        updated = 0
        for cache in caches.iterator(chunk_size=batch_size):
            payload_compressed = services.compress_overview_payload(
                cache.payload_json,
            )
            update_query = PagesOverviewCache.objects.filter(
                pk=cache.pk,
                generated_at=cache.generated_at,
            )
            if not options["force"]:
                update_query = update_query.filter(
                    payload_compressed__isnull=True,
                )
            updated += update_query.update(
                payload_compressed=payload_compressed,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Compressed {updated} Pages overview cache row(s).",
            )
        )
