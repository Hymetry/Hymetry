from statistics import mean, median
from time import perf_counter

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Sum

from apps.pages import company_analytics, company_detail_analytics, services
from apps.pages.models import CompaniesDetailCache, PageCompanyDailyMetric, PageUserDailyMetric
from apps.projects.models import Project


def _format_duration(seconds):
    seconds = float(seconds or 0)
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes, remainder = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {remainder:.0f}s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(minutes)}m {remainder:.0f}s"


def _timer():
    return perf_counter()


def _elapsed(start):
    return perf_counter() - start


def _company_id_from_payload(row):
    return str(row.get("companyId") or row.get("id") or "").strip()


class Command(BaseCommand):
    help = "Profile Companies overview/detail cache rebuild work without writing cache rows."

    def add_arguments(self, parser):
        parser.add_argument("--project-id", type=int)
        parser.add_argument("--range", dest="range_key", default="last_30_days")
        parser.add_argument(
            "--all-ranges",
            action="store_true",
            help="Profile all default analytics ranges.",
        )
        parser.add_argument(
            "--use-cache",
            action="store_true",
            help="Use existing Companies overview cache for detail sampling instead of rebuilding overview in memory.",
        )
        parser.add_argument(
            "--estimate-only",
            action="store_true",
            help="Only count source rows and estimated detail jobs. Does not build overview or detail payloads.",
        )
        parser.add_argument(
            "--sample-size",
            type=int,
            default=8,
            help="Number of companies to sample for detail payload timing. Use 0 to skip detail sampling.",
        )
        parser.add_argument(
            "--company-id",
            action="append",
            default=[],
            help="Specific company id to profile. Can be passed more than once.",
        )

    def handle(self, *args, **options):
        project_id = options["project_id"]
        if not project_id:
            raise CommandError("Provide --project-id.")

        project = Project.active.filter(pk=project_id).first()
        if project is None:
            raise CommandError(f"Project {project_id} does not exist.")

        sample_size = int(options["sample_size"])
        if sample_size < 0:
            raise CommandError("--sample-size must be zero or greater.")

        range_keys = services.DEFAULT_OVERVIEW_RANGE_KEYS if options["all_ranges"] else (options["range_key"],)
        explicit_company_ids = [str(value).strip() for value in options["company_id"] if str(value).strip()]

        self.stdout.write(
            f'Profiling Companies cache rebuild for project {project.id} "{project.name}". '
            "No cache rows will be written."
        )

        for range_key in range_keys:
            self._profile_range(
                project,
                range_key,
                use_cache=options["use_cache"],
                estimate_only=options["estimate_only"],
                sample_size=sample_size,
                explicit_company_ids=explicit_company_ids,
            )

    def _profile_range(self, project, range_key, *, use_cache, estimate_only, sample_size, explicit_company_ids):
        start_date, end_date = services.resolve_period(project.timezone, range_key=range_key)
        self.stdout.write("")
        self.stdout.write(f"Range {range_key}: {start_date.isoformat()} .. {end_date.isoformat()}")

        stats_start = _timer()
        row_stats = self._source_row_stats(project.id, start_date, end_date)
        self.stdout.write(
            "Source rows: "
            f"company_daily={row_stats['company_metric_rows']:,}, "
            f"user_daily={row_stats['user_metric_rows']:,}, "
            f"companies={row_stats['companies_count']:,}, "
            f"users={row_stats['users_count']:,} "
            f"({ _format_duration(_elapsed(stats_start)) })"
        )

        if estimate_only:
            detail_jobs = row_stats["companies_count"]
            current_detail_cache = CompaniesDetailCache.objects.filter(
                project_id=project.id,
                range_key=range_key,
                filters_hash=services.DEFAULT_FILTERS_HASH,
                payload_json__schema_version=company_detail_analytics.COMPANY_DETAIL_PAYLOAD_SCHEMA_VERSION,
            ).count()
            missing_or_stale_detail_jobs = max(0, detail_jobs - current_detail_cache)
            self.stdout.write(
                "Estimated cache work: "
                f"overview_jobs=1, "
                f"detail_jobs={detail_jobs:,}, "
                f"current_detail_cache_rows={current_detail_cache:,}, "
                f"missing_or_old_detail_jobs~={missing_or_stale_detail_jobs:,}"
            )
            self._print_heaviest_companies(project.id, start_date, end_date, limit=min(sample_size or 8, 20))
            return

        overview_payload = None
        overview_source = "built"
        overview_seconds = 0
        if use_cache:
            cache_start = _timer()
            cached = company_analytics.get_cached_companies_overview_payload(project.id, range_key=range_key)
            overview_seconds = _elapsed(cache_start)
            if cached:
                overview_payload = cached.get("payload_json") or {}
                overview_source = (
                    f"cache schema={cached.get('schema_version')} "
                    f"stale={bool(cached.get('is_stale'))}"
                )
            else:
                self.stdout.write(self.style.WARNING("No overview cache found; building overview payload in memory."))

        if overview_payload is None:
            overview_start = _timer()
            overview_payload = company_analytics.build_companies_overview_payload(project, range_key=range_key)
            overview_seconds = _elapsed(overview_start)

        overview_companies = overview_payload.get("companies") or []
        self.stdout.write(
            "Overview payload: "
            f"source={overview_source}, "
            f"time={_format_duration(overview_seconds)}, "
            f"companies={len(overview_companies):,}, "
            f"scatter_points={len((overview_payload.get('scatter') or {}).get('points') or []):,}"
        )

        if sample_size <= 0:
            return

        company_ids = self._sample_company_ids(
            project.id,
            start_date,
            end_date,
            overview_companies,
            sample_size=sample_size,
            explicit_company_ids=explicit_company_ids,
        )
        if not company_ids:
            self.stdout.write(self.style.WARNING("No companies available for detail sampling."))
            return

        self.stdout.write(f"Detail sample: {len(company_ids)} companies")
        samples = []
        for company_id in company_ids:
            detail_start = _timer()
            payload, _company_rows, _product_areas = company_detail_analytics.build_company_detail_payload(
                project,
                company_id,
                range_key=range_key,
                overview_payload=overview_payload,
            )
            seconds = _elapsed(detail_start)
            payload = payload or {}
            samples.append(seconds)
            self.stdout.write(
                f"- {company_id}: {_format_duration(seconds)}, "
                f"users={len(payload.get('users') or []):,}, "
                f"top_pages={len(payload.get('topPages') or []):,}, "
                f"peer_rows={len((payload.get('peerComparison') or {}).get('rows') or []):,}"
            )

        avg_seconds = mean(samples)
        median_seconds = median(samples)
        estimated_detail_seconds = avg_seconds * len(overview_companies)
        self.stdout.write(
            "Detail sample summary: "
            f"avg={_format_duration(avg_seconds)}, "
            f"median={_format_duration(median_seconds)}, "
            f"estimated_all_details={_format_duration(estimated_detail_seconds)}"
        )
        if estimated_detail_seconds > overview_seconds * 2:
            self.stdout.write(self.style.WARNING("Likely bottleneck: per-company detail cache hydration."))
        elif overview_seconds > estimated_detail_seconds:
            self.stdout.write(self.style.WARNING("Likely bottleneck: Companies overview payload build."))

    def _print_heaviest_companies(self, project_id, start_date, end_date, *, limit):
        if limit <= 0:
            return

        rows = list(
            PageUserDailyMetric.objects
            .filter(project_id=project_id, date__gte=start_date, date__lte=end_date)
            .exclude(company_id__isnull=True)
            .exclude(company_id="")
            .values("company_id")
            .annotate(
                metric_rows=Count("id"),
                users=Count("user_id", distinct=True),
                visits=Sum("visits_count"),
                engaged=Sum("engaged_seconds"),
            )
            .order_by("-metric_rows", "-users", "-engaged")[:limit]
        )
        if not rows:
            return

        self.stdout.write(f"Heaviest companies by user_daily rows, top {len(rows)}:")
        for row in rows:
            self.stdout.write(
                f"- {row['company_id']}: "
                f"user_daily_rows={int(row.get('metric_rows') or 0):,}, "
                f"users={int(row.get('users') or 0):,}, "
                f"visits={int(row.get('visits') or 0):,}, "
                f"engaged={int(row.get('engaged') or 0):,}"
            )

    def _source_row_stats(self, project_id, start_date, end_date):
        company_qs = PageCompanyDailyMetric.objects.filter(
            project_id=project_id,
            date__gte=start_date,
            date__lte=end_date,
        )
        user_qs = (
            PageUserDailyMetric.objects
            .filter(project_id=project_id, date__gte=start_date, date__lte=end_date)
            .exclude(company_id__isnull=True)
            .exclude(company_id="")
        )
        return {
            "company_metric_rows": company_qs.count(),
            "user_metric_rows": user_qs.count(),
            "companies_count": company_qs.values("company_id").distinct().count(),
            "users_count": user_qs.values("user_id").distinct().count(),
        }

    def _sample_company_ids(
        self,
        project_id,
        start_date,
        end_date,
        overview_companies,
        *,
        sample_size,
        explicit_company_ids,
    ):
        if explicit_company_ids:
            return explicit_company_ids[:sample_size or len(explicit_company_ids)]

        top_by_user_rows = list(
            PageUserDailyMetric.objects
            .filter(project_id=project_id, date__gte=start_date, date__lte=end_date)
            .exclude(company_id__isnull=True)
            .exclude(company_id="")
            .values("company_id")
            .annotate(
                metric_rows=Count("id"),
                users=Count("user_id", distinct=True),
                visits=Sum("visits_count"),
                engaged=Sum("engaged_seconds"),
            )
            .order_by("-metric_rows", "-users", "-engaged")[:sample_size]
        )
        company_ids = [str(row["company_id"]) for row in top_by_user_rows if row.get("company_id")]
        if len(company_ids) >= sample_size:
            return company_ids

        seen = set(company_ids)
        for row in overview_companies:
            company_id = _company_id_from_payload(row)
            if company_id and company_id not in seen:
                company_ids.append(company_id)
                seen.add(company_id)
            if len(company_ids) >= sample_size:
                break
        return company_ids
