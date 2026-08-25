from django.db import models

from apps.projects.models import Project


class ProductArea(models.Model):
    SOURCE_AI = 'ai'
    SOURCE_MANUAL = 'manual'
    SOURCE_SYSTEM = 'system'
    AREA_ROLE_PRODUCT = 'product'
    AREA_ROLE_SETUP = 'setup'
    AREA_ROLE_ADMIN = 'admin'
    AREA_ROLE_SUPPORT = 'support'
    AREA_ROLE_SYSTEM = 'system'
    AREA_ROLE_UNKNOWN = 'unknown'

    SOURCE_CHOICES = (
        (SOURCE_AI, 'AI'),
        (SOURCE_MANUAL, 'Manual'),
        (SOURCE_SYSTEM, 'System'),
    )
    AREA_ROLE_CHOICES = (
        (AREA_ROLE_PRODUCT, 'Product'),
        (AREA_ROLE_SETUP, 'Setup'),
        (AREA_ROLE_ADMIN, 'Admin'),
        (AREA_ROLE_SUPPORT, 'Support'),
        (AREA_ROLE_SYSTEM, 'System'),
        (AREA_ROLE_UNKNOWN, 'Unknown'),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='pages_product_areas')
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    short_name = models.CharField(max_length=64, blank=True, default='')
    color = models.CharField(max_length=32, blank=True, default='')
    category = models.CharField(max_length=255, blank=True, default='')
    category_color = models.CharField(max_length=32, blank=True, default='')
    description = models.TextField(blank=True, default='')
    area_role = models.CharField(max_length=16, choices=AREA_ROLE_CHOICES, default=AREA_ROLE_UNKNOWN)
    is_adoption_recommendable = models.BooleanField(default=False)
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_SYSTEM)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['project', 'slug'], name='pages_product_area_project_slug_uniq'),
        ]
        indexes = [
            models.Index(fields=['project', 'name'], name='pages_pa_project_name_idx'),
        ]

    def __str__(self):
        return f'{self.name} ({self.project_id})'


class PageVisit(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='pages_visits')
    session_id = models.UUIDField()
    visitor_guid = models.UUIDField(null=True, blank=True)
    user_id = models.CharField(max_length=255, null=True, blank=True)
    user_name_sample = models.CharField(max_length=255, blank=True, default='')
    company_id = models.CharField(max_length=255, null=True, blank=True)
    company_name_sample = models.CharField(max_length=255, blank=True, default='')
    url_normalized = models.TextField(blank=True, default='')
    page_name_original = models.CharField(max_length=255, blank=True, default='')
    page_rule_id = models.BigIntegerField(null=True, blank=True)
    product_area = models.ForeignKey(ProductArea, on_delete=models.SET_NULL, null=True, blank=True)
    product_area_key = models.SlugField(max_length=255, blank=True, default='')
    product_area_name = models.CharField(max_length=255, blank=True, default='')
    visit_start_ts = models.DateTimeField()
    visit_end_ts = models.DateTimeField()
    engaged_seconds = models.PositiveBigIntegerField(default=0)
    click_count = models.PositiveIntegerField(default=0)
    scroll_count = models.PositiveIntegerField(default=0)
    mouse_move_count = models.PositiveIntegerField(default=0)
    key_press_count = models.PositiveIntegerField(default=0)
    touch_move_count = models.PositiveIntegerField(default=0)
    had_click = models.BooleanField(default=False)
    had_scroll = models.BooleanField(default=False)
    had_mouse_move = models.BooleanField(default=False)
    had_key_press = models.BooleanField(default=False)
    had_touch_move = models.BooleanField(default=False)
    first_event_id = models.BigIntegerField(null=True, blank=True)
    last_event_id = models.BigIntegerField(null=True, blank=True)
    # Set false for a visit belonging to a completed low-confidence anonymous
    # session, which the daily rollups then skip.  The row itself is kept, so
    # changing the rule is a rebuild rather than a re-collection.  See
    # apps.tracker.analytics_eligibility for the rule and
    # apps.pages.queries.UPDATE_LOW_CONFIDENCE_VISITS_SQL for how it is set.
    is_analytics_eligible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['project', 'visit_start_ts'], name='pages_visit_project_start_idx'),
            models.Index(fields=['project', 'product_area', 'visit_start_ts'], name='pages_visit_area_start_idx'),
            models.Index(fields=['project', 'session_id', 'visit_start_ts'], name='pages_visit_session_idx'),
            models.Index(fields=['project', 'company_id', 'visit_start_ts'], name='pages_visit_company_idx'),
            models.Index(fields=['project', 'user_id', 'visit_start_ts'], name='pages_visit_user_idx'),
        ]

    def __str__(self):
        return f'{self.product_area_name or self.url_normalized} visit {self.id}'


class PageTransition(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='pages_transitions')
    session_id = models.UUIDField()
    company_id = models.CharField(max_length=255, null=True, blank=True)
    user_id = models.CharField(max_length=255, null=True, blank=True)
    from_visit = models.ForeignKey(PageVisit, on_delete=models.CASCADE, related_name='outgoing_transitions')
    to_visit = models.ForeignKey(PageVisit, on_delete=models.CASCADE, related_name='incoming_transitions')
    from_page_rule_id = models.BigIntegerField(null=True, blank=True)
    to_page_rule_id = models.BigIntegerField(null=True, blank=True)
    from_product_area = models.ForeignKey(ProductArea, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    to_product_area = models.ForeignKey(ProductArea, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    from_product_area_key = models.SlugField(max_length=255, blank=True, default='')
    to_product_area_key = models.SlugField(max_length=255, blank=True, default='')
    from_product_area_name = models.CharField(max_length=255, blank=True, default='')
    to_product_area_name = models.CharField(max_length=255, blank=True, default='')
    from_url_normalized = models.TextField(blank=True, default='')
    to_url_normalized = models.TextField(blank=True, default='')
    transition_ts = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=['project', 'transition_ts'], name='pages_trans_project_ts_idx'),
            models.Index(fields=['project', 'from_product_area', 'to_product_area'], name='pages_trans_area_pair_idx'),
            models.Index(fields=['project', 'from_page_rule_id', 'transition_ts'], name='pages_trans_from_rule_ts_idx'),
            models.Index(fields=['project', 'to_page_rule_id', 'transition_ts'], name='pages_trans_to_rule_ts_idx'),
        ]


class PageDailyMetric(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='pages_daily_metrics')
    date = models.DateField()
    page_rule_id = models.BigIntegerField(null=True, blank=True)
    product_area = models.ForeignKey(ProductArea, on_delete=models.SET_NULL, null=True, blank=True)
    product_area_key = models.SlugField(max_length=255, blank=True, default='')
    product_area_name = models.CharField(max_length=255, blank=True, default='')
    visits_count = models.PositiveBigIntegerField(default=0)
    engaged_seconds = models.PositiveBigIntegerField(default=0)
    click_count = models.PositiveBigIntegerField(default=0)
    scroll_count = models.PositiveBigIntegerField(default=0)
    mouse_move_count = models.PositiveBigIntegerField(default=0)
    key_press_count = models.PositiveBigIntegerField(default=0)
    touch_move_count = models.PositiveBigIntegerField(default=0)
    visits_with_click_count = models.PositiveBigIntegerField(default=0)
    companies_count_daily = models.PositiveBigIntegerField(default=0)
    users_count_daily = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'date', 'page_rule_id', 'product_area_key'],
                name='pages_pdm_project_date_rule_area_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['project', 'date'], name='pages_pdm_project_date_idx'),
            models.Index(fields=['project', 'product_area', 'date'], name='pages_pdm_area_date_idx'),
            models.Index(fields=['project', 'page_rule_id', 'date'], name='pages_pdm_rule_date_idx'),
        ]


class PageCompanyDailyMetric(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='pages_company_daily_metrics')
    date = models.DateField()
    page_rule_id = models.BigIntegerField(null=True, blank=True)
    product_area = models.ForeignKey(ProductArea, on_delete=models.SET_NULL, null=True, blank=True)
    product_area_key = models.SlugField(max_length=255, blank=True, default='')
    product_area_name = models.CharField(max_length=255, blank=True, default='')
    company_id = models.CharField(max_length=255)
    company_name_sample = models.CharField(max_length=255, blank=True, default='')
    visits_count = models.PositiveBigIntegerField(default=0)
    engaged_seconds = models.PositiveBigIntegerField(default=0)
    click_count = models.PositiveBigIntegerField(default=0)
    visits_with_click_count = models.PositiveBigIntegerField(default=0)
    active_users_count_daily = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'date', 'page_rule_id', 'product_area_key', 'company_id'],
                name='pages_pcdm_project_date_rule_company_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['project', 'date', 'company_id'], name='pages_pcdm_date_company_idx'),
            models.Index(fields=['project', 'company_id', 'date'], name='pages_pcdm_proj_comp_date_idx'),
            models.Index(fields=['project', 'product_area', 'date'], name='pages_pcdm_area_date_idx'),
            models.Index(fields=['project', 'page_rule_id', 'date'], name='pages_pcdm_rule_date_idx'),
        ]


class PageUserDailyMetric(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='pages_user_daily_metrics')
    date = models.DateField()
    page_rule_id = models.BigIntegerField(null=True, blank=True)
    product_area = models.ForeignKey(ProductArea, on_delete=models.SET_NULL, null=True, blank=True)
    product_area_key = models.SlugField(max_length=255, blank=True, default='')
    product_area_name = models.CharField(max_length=255, blank=True, default='')
    company_id = models.CharField(max_length=255, null=True, blank=True)
    user_id = models.CharField(max_length=255)
    user_name_sample = models.CharField(max_length=255, blank=True, default='')
    visits_count = models.PositiveBigIntegerField(default=0)
    engaged_seconds = models.PositiveBigIntegerField(default=0)
    click_count = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'date', 'page_rule_id', 'product_area_key', 'user_id'],
                name='pages_pudm_project_date_rule_user_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['project', 'date', 'user_id'], name='pages_pudm_date_user_idx'),
            models.Index(fields=['project', 'company_id', 'date'], name='pages_pudm_proj_comp_date_idx'),
            models.Index(fields=['project', 'company_id', 'user_id'], name='pages_pudm_proj_comp_user_idx'),
            models.Index(fields=['project', 'product_area', 'date'], name='pages_pudm_area_date_idx'),
            models.Index(fields=['project', 'page_rule_id', 'date'], name='pages_pudm_rule_date_idx'),
        ]


class RawPageDailyMetric(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='pages_raw_daily_metrics')
    date = models.DateField()
    url_normalized = models.TextField()
    page_rule_id = models.BigIntegerField(null=True, blank=True)
    product_area = models.ForeignKey(ProductArea, on_delete=models.SET_NULL, null=True, blank=True)
    product_area_key = models.SlugField(max_length=255, blank=True, default='')
    product_area_name = models.CharField(max_length=255, blank=True, default='')
    page_label = models.CharField(max_length=255, blank=True, default='')
    page_title_sample = models.CharField(max_length=255, blank=True, default='')
    visits_count = models.PositiveBigIntegerField(default=0)
    engaged_seconds = models.PositiveBigIntegerField(default=0)
    click_count = models.PositiveBigIntegerField(default=0)
    visits_with_click_count = models.PositiveBigIntegerField(default=0)
    companies_count_daily = models.PositiveBigIntegerField(default=0)
    users_count_daily = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['project', 'date', 'url_normalized'], name='pages_rpdm_project_date_url_uniq'),
        ]
        indexes = [
            models.Index(fields=['project', 'date'], name='pages_rpdm_project_date_idx'),
            models.Index(fields=['project', 'page_rule_id', 'date'], name='pages_rpdm_rule_date_idx'),
        ]


class RawPageActionDailyMetric(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='pages_raw_action_daily_metrics')
    date = models.DateField()
    url_normalized = models.TextField()
    page_rule_id = models.BigIntegerField(null=True, blank=True)
    product_area = models.ForeignKey(ProductArea, on_delete=models.SET_NULL, null=True, blank=True)
    product_area_key = models.SlugField(max_length=255, blank=True, default='')
    product_area_name = models.CharField(max_length=255, blank=True, default='')
    element_key = models.CharField(max_length=300)
    clicks_count = models.PositiveBigIntegerField(default=0)
    users_count_daily = models.PositiveBigIntegerField(default=0)
    companies_count_daily = models.PositiveBigIntegerField(default=0)
    visits_with_action_count = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'date', 'url_normalized', 'element_key'],
                name='pages_rpadm_project_date_url_element_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['project', 'date'], name='pages_rpadm_project_date_idx'),
            models.Index(fields=['project', 'page_rule_id', 'date'], name='pages_rpadm_rule_date_idx'),
        ]


class ProjectDailyMetric(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='pages_project_daily_metrics')
    date = models.DateField()
    active_companies_count = models.PositiveBigIntegerField(default=0)
    active_users_count = models.PositiveBigIntegerField(default=0)
    visits_count = models.PositiveBigIntegerField(default=0)
    engaged_seconds = models.PositiveBigIntegerField(default=0)
    click_count = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['project', 'date'], name='pages_prdm_project_date_uniq'),
        ]
        indexes = [
            models.Index(fields=['project', 'date'], name='pages_prdm_project_date_idx'),
        ]


class PagesCompanyAnalyticsManifest(models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='pages_company_analytics_manifests',
    )
    range_key = models.CharField(max_length=64)
    start_date = models.DateField()
    end_date = models.DateField()
    analytics_facts_revision = models.PositiveBigIntegerField()
    schema_version = models.PositiveIntegerField(default=1)
    payload_format = models.CharField(max_length=32, default='json')
    company_count = models.PositiveIntegerField(default=0)
    payload_bytes = models.PositiveBigIntegerField(default=0)
    source_max_event_ts = models.DateTimeField(null=True, blank=True)
    generated_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'project',
                    'range_key',
                    'start_date',
                    'end_date',
                    'analytics_facts_revision',
                ],
                name='pages_cmpfact_manifest_uniq',
            ),
        ]
        indexes = [
            models.Index(
                fields=['project', 'range_key', 'analytics_facts_revision'],
                name='pages_cmpfact_lookup_idx',
            ),
        ]


class PagesCompanyAnalyticsFragment(models.Model):
    manifest = models.ForeignKey(
        PagesCompanyAnalyticsManifest,
        on_delete=models.CASCADE,
        related_name='fragments',
    )
    company_key = models.CharField(max_length=255)
    company_id = models.CharField(max_length=255, null=True, blank=True)
    company_name_sample = models.CharField(max_length=255, blank=True, default='')
    payload_json = models.JSONField(default=dict, blank=True)
    payload_binary = models.BinaryField(null=True, blank=True, editable=False)
    payload_bytes = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['manifest', 'company_key'],
                name='pages_cmpfrag_key_uniq',
            ),
        ]
        indexes = [
            models.Index(
                fields=['manifest', 'company_id'],
                name='pages_cmpfrag_company_idx',
            ),
            models.Index(
                fields=['manifest', 'company_key'],
                name='pages_cmpfrag_lookup_idx',
            ),
        ]


class PagesOverviewCache(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='pages_overview_caches')
    range_key = models.CharField(max_length=64)
    start_date = models.DateField()
    end_date = models.DateField()
    filters_hash = models.CharField(max_length=64, default='default')
    payload_json = models.JSONField(default=dict, blank=True)
    payload_compressed = models.BinaryField(null=True, blank=True, editable=False)
    source_max_event_ts = models.DateTimeField(null=True, blank=True)
    generated_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    is_stale = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['project', 'range_key', 'filters_hash'], name='pages_overview_cache_uniq'),
        ]
        indexes = [
            models.Index(fields=['project', 'range_key'], name='pages_cache_project_range_idx'),
            models.Index(fields=['project', 'generated_at'], name='pages_cache_project_gen_idx'),
        ]


class CompaniesOverviewCache(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='companies_overview_caches')
    range_key = models.CharField(max_length=64)
    start_date = models.DateField()
    end_date = models.DateField()
    filters_hash = models.CharField(max_length=64, default='default')
    payload_json = models.JSONField(default=dict, blank=True)
    source_max_event_ts = models.DateTimeField(null=True, blank=True)
    generated_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    is_stale = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['project', 'range_key', 'filters_hash'], name='companies_overview_cache_uniq'),
        ]
        indexes = [
            models.Index(fields=['project', 'range_key'], name='comp_cache_proj_rng_idx'),
            models.Index(fields=['project', 'generated_at'], name='comp_cache_proj_gen_idx'),
        ]


class UsersOverviewCache(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='users_overview_caches')
    range_key = models.CharField(max_length=64)
    start_date = models.DateField()
    end_date = models.DateField()
    filters_hash = models.CharField(max_length=64, default='default')
    payload_json = models.JSONField(default=dict, blank=True)
    source_max_event_ts = models.DateTimeField(null=True, blank=True)
    generated_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    is_stale = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['project', 'range_key', 'filters_hash'], name='users_overview_cache_uniq'),
        ]
        indexes = [
            models.Index(fields=['project', 'range_key'], name='users_cache_proj_rng_idx'),
            models.Index(fields=['project', 'generated_at'], name='users_cache_proj_gen_idx'),
        ]


class UsersDetailCache(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='users_detail_caches')
    range_key = models.CharField(max_length=64)
    user_id = models.CharField(max_length=255)
    start_date = models.DateField()
    end_date = models.DateField()
    filters_hash = models.CharField(max_length=64, default='default')
    payload_json = models.JSONField(default=dict, blank=True)
    generated_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    is_stale = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'range_key', 'user_id', 'filters_hash'],
                name='users_detail_cache_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['project', 'range_key', 'user_id'], name='users_det_proj_range_idx'),
            models.Index(fields=['project', 'generated_at'], name='users_det_proj_gen_idx'),
        ]


class CompaniesDetailCache(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='companies_detail_caches')
    range_key = models.CharField(max_length=64)
    company_id = models.CharField(max_length=255)
    start_date = models.DateField()
    end_date = models.DateField()
    filters_hash = models.CharField(max_length=64, default='default')
    payload_json = models.JSONField(default=dict, blank=True)
    generated_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    is_stale = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'range_key', 'company_id', 'filters_hash'],
                name='companies_detail_cache_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['project', 'range_key', 'company_id'], name='comp_det_proj_range_idx'),
            models.Index(fields=['project', 'generated_at'], name='comp_det_proj_gen_idx'),
        ]


class PagesDetailCache(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='pages_detail_caches')
    range_key = models.CharField(max_length=64)
    page_rule_id = models.CharField(max_length=255)
    start_date = models.DateField()
    end_date = models.DateField()
    filters_hash = models.CharField(max_length=64, default='default')
    payload_json = models.JSONField(default=dict, blank=True)
    generated_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    is_stale = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'range_key', 'page_rule_id', 'filters_hash'],
                name='pages_detail_cache_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['project', 'range_key', 'page_rule_id'], name='pages_det_proj_range_idx'),
            models.Index(fields=['project', 'generated_at'], name='pages_det_proj_gen_idx'),
        ]


class PagesScatterTooltipCache(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='pages_scatter_tooltip_caches')
    range_key = models.CharField(max_length=64)
    start_date = models.DateField()
    end_date = models.DateField()
    filters_hash = models.CharField(max_length=64, default='default')
    payload_json = models.JSONField(default=dict, blank=True)
    generated_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    is_stale = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['project', 'range_key', 'filters_hash'], name='pages_scatter_cache_uniq'),
        ]
        indexes = [
            models.Index(fields=['project', 'range_key'], name='pages_scat_proj_range_idx'),
        ]
