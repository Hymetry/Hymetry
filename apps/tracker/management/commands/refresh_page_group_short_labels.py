from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.text import slugify

from apps.pages import services
from apps.pages.models import ProductArea
from apps.projects.models import Project
from apps.tracker.models import (
    ProjectPageNamingPhase,
    ProjectPageNamingRun,
    ProjectPageNamingRunMode,
    ProjectPageNamingRunStatus,
    ProjectPageRuleVersion,
)
from apps.tracker.page_naming import (
    _serialize_rules_for_snapshot,
    apply_rules_to_analytics_events,
    build_hybrid_urls,
    generate_page_naming_rules,
    get_active_page_rules,
    get_source_adapter,
    normalize_product_area,
    normalize_product_area_short_name,
    replace_project_page_rules,
)


class Command(BaseCommand):
    help = (
        'Force-refresh page group short labels by running one page-naming LLM request, '
        'then rebuild prepared analytics, Companies cache, and Users cache.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--project-id', type=int)
        parser.add_argument(
            '--mode',
            choices=[
                ProjectPageNamingRunMode.HOURLY_UNSTABLE,
                ProjectPageNamingRunMode.DAILY_STABLE,
            ],
            default=ProjectPageNamingRunMode.DAILY_STABLE,
            help='Prompt/mode to use for the forced LLM refresh. Default: daily_stable.',
        )
        parser.add_argument(
            '--history-days',
            type=int,
            default=360,
            help='How many recent local days to re-apply rules and rebuild prepared analytics for. Default: 360.',
        )
        parser.add_argument(
            '--model',
            default='',
            help='Override the TitlePrompt model for this one run without changing the database.',
        )
        parser.add_argument(
            '--reuse-active-rules',
            action='store_true',
            help='Skip the LLM call and sync short labels from currently active rules.',
        )
        parser.add_argument(
            '--skip-analytics-backfill',
            action='store_true',
            help='Only update active rules, ProductArea short names, Companies cache, and Users cache.',
        )

    def handle(self, *args, **options):
        project = self._resolve_project(options)
        history_days = options['history_days']
        if history_days <= 0:
            raise CommandError('--history-days must be greater than zero.')

        mode = options['mode']
        phase = (
            ProjectPageNamingPhase.STABLE
            if mode == ProjectPageNamingRunMode.DAILY_STABLE
            else ProjectPageNamingPhase.INCREMENTAL
        )
        now = timezone.now()
        active_rules = get_active_page_rules(project)
        reuse_active_rules = options['reuse_active_rules']
        if reuse_active_rules:
            if not active_rules:
                raise CommandError('No active page rules available to reuse.')
            urls = []
            unique_urls_total = 0
        else:
            adapter = get_source_adapter(project)
            urls = build_hybrid_urls(project, adapter, now=now)
            if not urls:
                raise CommandError('No URLs available for page naming prompt.')
            unique_urls_total = adapter.unique_urls_total()

        run = ProjectPageNamingRun.objects.create(
            project=project,
            mode=mode,
            phase=phase,
            status=ProjectPageNamingRunStatus.SKIPPED,
            input_urls_count=len(urls),
            unique_urls_total=unique_urls_total,
        )

        try:
            if reuse_active_rules:
                created_rules = list(active_rules)
                ai_result = {
                    'prompt_name': 'active_rules:reuse',
                    'prompt_version': 'existing',
                    'payload': {},
                }
                llm_calls = 0
            else:
                existing_rules = _serialize_rules_for_snapshot(active_rules)
                ai_result = generate_page_naming_rules(
                    project,
                    mode,
                    urls,
                    existing_rules=existing_rules,
                    model_name=(options['model'] or '').strip() or None,
                    run=run,
                    phase=phase,
                )
                if not ai_result['rules']:
                    raise CommandError('AI returned no valid rules.')

                created_rules = replace_project_page_rules(project, ai_result['rules'], mode)
                ProjectPageRuleVersion.objects.create(
                    project=project,
                    run=run,
                    mode=mode,
                    phase=phase,
                    rules_json=_serialize_rules_for_snapshot(created_rules),
                    ai_response_json=ai_result['payload'],
                )
                llm_calls = 1

            start_date, end_date = self._history_window(project, history_days)
            product_areas_synced = self._sync_product_area_short_names(project, created_rules)

            if options['skip_analytics_backfill']:
                events_updated = 0
                cache_result = services.rebuild_project_analytics_caches(project.id)
                companies_cache_results = cache_result.get('companies_cache_results') or []
                users_cache_results = cache_result.get('users_cache_results') or []
                analytics_result = {
                    'status': 'skipped',
                    'cache_status': cache_result.get('status'),
                }
            else:
                since, _ = services._utc_bounds_for_local_dates(start_date, end_date, project.timezone or 'UTC')
                events_updated = apply_rules_to_analytics_events(project, created_rules, since)
                analytics_result = services.rebuild_project_pages_analytics(
                    project.id,
                    start_date,
                    end_date,
                )
                companies_cache_results = analytics_result.get('companies_cache_results') or []
                users_cache_results = analytics_result.get('users_cache_results') or []

            run.status = ProjectPageNamingRunStatus.SUCCESS
            run.prompt_name = ai_result['prompt_name']
            run.prompt_version = ai_result['prompt_version']
            run.output_rules_count = len(created_rules)
            run.finished_at = timezone.now()
            run.save(
                update_fields=[
                    'status',
                    'prompt_name',
                    'prompt_version',
                    'output_rules_count',
                    'finished_at',
                ]
            )
        except Exception as exc:
            run.status = ProjectPageNamingRunStatus.FAILED
            run.error_message = str(exc)
            run.finished_at = timezone.now()
            run.save(update_fields=['status', 'error_message', 'finished_at'])
            if isinstance(exc, CommandError):
                raise
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                'Page group short labels refreshed: '
                f'project_id={project.id}, llm_calls={llm_calls}, rules={len(created_rules)}, '
                f'product_areas_synced={product_areas_synced}, events_updated={events_updated}, '
                f'analytics_status={analytics_result.get("status")}, '
                f'companies_caches={len(companies_cache_results)}, '
                f'users_caches={len(users_cache_results)}'
            )
        )

    def _resolve_project(self, options):
        project_id = options['project_id']
        if not project_id:
            raise CommandError('Provide --project-id.')

        project = Project.active.filter(pk=project_id).first()
        if project is None:
            raise CommandError(f'Project {project_id} does not exist.')
        return project

    def _history_window(self, project, history_days):
        end_date = services._today_for_project(project.timezone or 'UTC')
        start_date = end_date - timedelta(days=history_days - 1)
        return start_date, end_date

    def _sync_product_area_short_names(self, project, rules):
        synced = 0
        seen_slugs = set()

        for rule in rules:
            product_area = normalize_product_area(rule.product_area, rule.page_name)
            short_name = normalize_product_area_short_name(rule.product_area_short_name, product_area)
            slug = slugify(product_area) or 'unassigned'
            if not product_area or not short_name or slug in seen_slugs:
                continue

            seen_slugs.add(slug)
            ProductArea.objects.update_or_create(
                project=project,
                slug=slug,
                defaults={
                    'name': product_area,
                    'short_name': short_name,
                    'source': ProductArea.SOURCE_AI,
                },
            )
            synced += 1

        return synced
