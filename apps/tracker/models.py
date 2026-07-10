import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.projects.models import Project

COMMON_OPENAI_CHAT_MODELS = [
    'gpt-5.4',
    'gpt-5.4-mini',
    'gpt-5.4-nano',
    'o3',
    'o3-mini'
]


class ProjectPageNamingRunMode(models.TextChoices):
    HOURLY_UNSTABLE = 'hourly_unstable', 'Hourly unstable'
    DAILY_STABLE = 'daily_stable', 'Daily stable'
    HOURLY_TITLE_BACKFILL = 'hourly_backfill', 'Hourly title backfill'


class ProjectPageNamingRunStatus(models.TextChoices):
    SUCCESS = 'success', 'Success'
    SKIPPED = 'skipped', 'Skipped'
    FAILED = 'failed', 'Failed'


class ProjectPageNamingPhase(models.TextChoices):
    BOOTSTRAP = 'bootstrap', 'Bootstrap'
    INCREMENTAL = 'incremental', 'Incremental'
    STABLE = 'stable', 'Stable'
    BACKFILL = 'backfill', 'Backfill'


class Visitor(models.Model):
    visitor_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    visitor_guid = models.UUIDField(null=True, blank=True, help_text="Visitor ID from browser")
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    first_visit = models.DateTimeField(default=timezone.now)
    last_activity = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ('visitor_guid', 'project')

    def __str__(self):
        return f"Visitor {self.visitor_id}"

    def update_activity(self):
        """Update visitor's last activity timestamp."""
        self.last_activity = timezone.now()
        self.save()


class Session(models.Model):
    session_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    visitor = models.ForeignKey(Visitor, on_delete=models.CASCADE, related_name='sessions', null=True)
    start_time = models.DateTimeField(default=timezone.now)
    last_activity = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['start_time'], name='trk_session_start_idx'),
            models.Index(fields=['visitor', 'start_time'], name='trk_sess_visit_start_idx'),
        ]

    def __str__(self):
        return f"Session {self.session_id}"

    @property
    def duration(self):
        if self.start_time and self.ended_at:
            return self.ended_at - self.start_time
        return None

    @property
    def is_active(self):
        """Check if a session is active.

        We rely solely on `self.last_activity` which is now updated only by user
        interactions (and not passive mutations).
        """
        reference_time = self.last_activity

        if not reference_time:
            return False

        return (timezone.now() - reference_time).total_seconds() < settings.SESSION_EXPIRATION_SECONDS

    def check_and_close_if_expired(self):
        """Check if session has expired and close it if necessary.

        We use `self.last_activity` as the reference time to align with `is_active`.
        """
        if not self.ended_at and not self.is_active:
            reference_time = self.last_activity or timezone.now()
            self.ended_at = reference_time + timezone.timedelta(seconds=settings.SESSION_EXPIRATION_SECONDS)
            self.save()

            # Clean up Redis data for this session
            self._cleanup_redis_data()

            return True
        return False

    def _cleanup_redis_data(self):
        """Clean up Redis data for this session"""
        try:
            from .redis_stateful_masking import cleanup_session_redis_data
            cleanup_session_redis_data(str(self.session_id))
        except Exception as e:
            # Log error but don't fail session close
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to cleanup Redis data for session {self.session_id}: {e}")

class Event(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='events', null=True)
    url = models.TextField(blank=True, default="")
    tab_id = models.CharField(max_length=36, help_text="Unique browser tab identifier", null=True)
    event_type = models.PositiveSmallIntegerField()
    timestamp = models.DateTimeField(default=timezone.now)
    data = models.JSONField()

    class Meta:
        indexes = [
            models.Index(fields=['session', 'timestamp'], name='trk_event_sess_ts_idx'),
            models.Index(fields=['session', 'url'], name='trk_event_sess_url_idx'),
        ]

    def __str__(self):
        return f"{self.event_type} at {self.timestamp}"


class AnalyticsSession(models.Model):
    session_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='analytics_sessions')
    visitor_guid = models.UUIDField(null=True, blank=True, help_text="Visitor ID from browser")
    user_id = models.CharField(max_length=255, null=True, blank=True)
    company_id = models.CharField(max_length=255, null=True, blank=True)
    start_time = models.DateTimeField(default=timezone.now)
    last_activity = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=['project', 'visitor_guid', 'user_id', 'company_id', 'ended_at'],
                name='tracker_anas_lookup_idx'
            ),
            models.Index(fields=['project', 'last_activity'], name='tracker_anas_activity_idx'),
        ]

    def __str__(self):
        return f"AnalyticsSession {self.session_id}"

    @property
    def is_active(self):
        if self.ended_at:
            return False

        reference_time = self.last_activity or self.start_time
        if not reference_time:
            return False

        timeout = getattr(settings, 'ANALYTICS_SESSION_EXPIRATION_SECONDS', 1800)
        return (timezone.now() - reference_time).total_seconds() < timeout


class AnalyticsEvent(models.Model):
    session = models.ForeignKey(AnalyticsSession, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=32, default='click')
    timestamp = models.DateTimeField(default=timezone.now)
    visitor_guid = models.UUIDField(null=True, blank=True)
    user_id = models.CharField(max_length=255, null=True, blank=True)
    company_id = models.CharField(max_length=255, null=True, blank=True)
    user_traits = models.JSONField(default=dict, blank=True)
    company_traits = models.JSONField(default=dict, blank=True)
    element_key = models.CharField(max_length=300, null=True, blank=True)
    url = models.TextField(blank=True, default="")
    url_normalized = models.TextField(blank=True, default="")
    product_area = models.CharField(max_length=255, blank=True, default='')
    page_name = models.CharField(max_length=255, default='Undefined')
    page_name_original = models.CharField(max_length=255, blank=True, default='')
    page_rule = models.ForeignKey(
        'ProjectPageRule',
        on_delete=models.SET_NULL,
        related_name='analytics_events',
        null=True,
        blank=True,
    )

    class Meta:
        indexes = [
            models.Index(fields=['session', 'timestamp'], name='tracker_anae_session_ts_idx'),
            models.Index(fields=['visitor_guid', 'timestamp'], name='tracker_anae_visitor_ts_idx'),
            models.Index(fields=['timestamp'], name='tracker_anae_timestamp_idx'),
            models.Index(fields=['url', 'timestamp'], name='trk_anae_url_ts_idx'),
        ]

    def __str__(self):
        return f"{self.event_type} at {self.timestamp}"


class ProjectPageRule(models.Model):
    AREA_ROLE_PRODUCT = 'product'
    AREA_ROLE_SETUP = 'setup'
    AREA_ROLE_ADMIN = 'admin'
    AREA_ROLE_SUPPORT = 'support'
    AREA_ROLE_SYSTEM = 'system'
    AREA_ROLE_UNKNOWN = 'unknown'
    AREA_ROLE_CHOICES = (
        (AREA_ROLE_PRODUCT, 'Product'),
        (AREA_ROLE_SETUP, 'Setup'),
        (AREA_ROLE_ADMIN, 'Admin'),
        (AREA_ROLE_SUPPORT, 'Support'),
        (AREA_ROLE_SYSTEM, 'System'),
        (AREA_ROLE_UNKNOWN, 'Unknown'),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='page_rules')
    pattern = models.TextField()
    product_area = models.CharField(max_length=255, blank=True, default='')
    product_area_short_name = models.CharField(max_length=64, blank=True, default='')
    area_role = models.CharField(max_length=16, choices=AREA_ROLE_CHOICES, default=AREA_ROLE_UNKNOWN)
    is_adoption_recommendable = models.BooleanField(default=False)
    page_name = models.CharField(max_length=255)
    priority = models.IntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_by = models.CharField(
        max_length=16,
        choices=ProjectPageNamingRunMode.choices,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-priority', '-updated_at', 'id']
        indexes = [
            models.Index(fields=['project', 'is_active', 'priority'], name='tracker_pgr_project_active_idx'),
        ]
        verbose_name = 'Page naming pattern'
        verbose_name_plural = 'Page naming patterns'

    def __str__(self):
        return f"{self.page_name} ({self.project_id})"


class ProjectPageNamingRun(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='page_naming_runs')
    mode = models.CharField(max_length=32, choices=ProjectPageNamingRunMode.choices)
    phase = models.CharField(
        max_length=16,
        choices=ProjectPageNamingPhase.choices,
        blank=True,
        default='',
    )
    status = models.CharField(max_length=16, choices=ProjectPageNamingRunStatus.choices)
    skip_reason = models.CharField(max_length=255, blank=True, default='')
    error_message = models.TextField(blank=True, default='')
    new_urls_1h = models.PositiveIntegerField(default=0)
    new_urls_24h = models.FloatField(default=0)
    unique_urls_total = models.PositiveIntegerField(default=0)
    events_1h = models.PositiveIntegerField(default=0)
    input_urls_count = models.PositiveIntegerField(default=0)
    output_rules_count = models.PositiveIntegerField(default=0)
    prompt_name = models.CharField(max_length=100, blank=True, default='')
    prompt_version = models.CharField(max_length=32, blank=True, default='')
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['project', 'started_at'], name='trk_pnr_proj_start_idx'),
        ]
        verbose_name = 'Page naming run'
        verbose_name_plural = 'Page naming runs'

    def __str__(self):
        return f"{self.project_id} {self.mode} {self.status}"


class LLMUsageLog(models.Model):
    RESULT_OK = 'ok'
    RESULT_ERROR = 'error'
    RESULT_CHOICES = (
        (RESULT_OK, 'OK'),
        (RESULT_ERROR, 'Error'),
    )

    feature = models.CharField(max_length=64, blank=True, default='')
    provider = models.CharField(max_length=32, blank=True, default='openai')
    operation = models.CharField(max_length=64, blank=True, default='chat.completions.create')
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        related_name='llm_usage_logs',
        null=True,
        blank=True,
    )
    page_naming_run = models.ForeignKey(
        ProjectPageNamingRun,
        on_delete=models.SET_NULL,
        related_name='llm_usage_logs',
        null=True,
        blank=True,
    )
    mode = models.CharField(max_length=32, blank=True, default='')
    model_name = models.CharField(max_length=100, blank=True, default='')
    prompt_name = models.CharField(max_length=100, blank=True, default='')
    prompt_version = models.CharField(max_length=32, blank=True, default='')
    result = models.CharField(max_length=16, choices=RESULT_CHOICES)
    duration_ms = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['project', 'created_at'], name='trk_llm_proj_created_idx'),
            models.Index(fields=['feature', 'created_at'], name='trk_llm_feat_created_idx'),
            models.Index(fields=['result', 'created_at'], name='trk_llm_res_created_idx'),
            models.Index(fields=['page_naming_run', 'created_at'], name='trk_llm_run_created_idx'),
        ]
        verbose_name = 'LLM usage log'
        verbose_name_plural = 'LLM usage logs'

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M:%S} {self.feature} {self.result}"


class ProjectPageRuleVersion(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='page_rule_versions')
    run = models.ForeignKey(ProjectPageNamingRun, on_delete=models.CASCADE, related_name='rule_versions')
    mode = models.CharField(max_length=32, choices=ProjectPageNamingRunMode.choices)
    phase = models.CharField(
        max_length=16,
        choices=ProjectPageNamingPhase.choices,
        blank=True,
        default='',
    )
    rules_json = models.JSONField(default=list, blank=True)
    ai_response_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['project', 'created_at'], name='trk_prv_proj_created_idx'),
        ]
        verbose_name = 'Page naming rule version'
        verbose_name_plural = 'Page naming rule versions'

    def __str__(self):
        return f"{self.project_id} {self.mode} {self.created_at:%Y-%m-%d %H:%M}"


class TitlePrompt(models.Model):
    name = models.CharField(max_length=100, unique=True)
    bootstrap_page_naming_prompt = models.TextField(blank=True, default='')
    bootstrap_page_naming_openai_model = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text='OpenAI model used for bootstrap page naming prompt.',
    )
    hourly_unstable_prompt = models.TextField(blank=True, default='')
    hourly_unstable_openai_model = models.CharField(
        max_length=100,
        help_text='OpenAI model used for the hourly unstable prompt.',
    )
    daily_stable_prompt = models.TextField(blank=True, default='')
    daily_stable_openai_model = models.CharField(
        max_length=100,
        help_text='OpenAI model used for the daily stable prompt.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if TitlePrompt.objects.exclude(pk=self.pk).exists():
            raise ValidationError('Only one TitlePrompt configuration is allowed.')

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class BubbleCache(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='bubbles', null=True)
    url = models.TextField(blank=True, default="")
    timestamp = models.DateTimeField(verbose_name="Hour and Minute")
    size = models.PositiveSmallIntegerField(verbose_name="Bubble size")
    clicks = models.PositiveSmallIntegerField(verbose_name="Click count")
    mouse_moves = models.PositiveSmallIntegerField(verbose_name="Mouse movements")
    key_strokes = models.PositiveSmallIntegerField(verbose_name="Key strokes")
    seconds_spent = models.PositiveIntegerField(verbose_name="Seconds spent on page", default=0)

    class Meta:
        indexes = [
            models.Index(fields=['session', 'timestamp'], name='trk_bcache_sess_ts_idx'),
            models.Index(fields=['session', 'url'], name='trk_bcache_sess_url_idx'),
        ]

    def __str__(self):
        return f"{self.url}, {self.size}"


class ProjectNormalizationFactor(models.Model):
    """Store normalization factors for projects to avoid recalculating them."""
    project = models.ForeignKey('projects.Project', on_delete=models.CASCADE, related_name='normalization_factors')
    factor = models.FloatField(help_text="Normalization factor (k) for bubble size calculations")
    calculated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-calculated_at']

    def __str__(self):
        return f"Project {self.project.id}: k={self.factor:.4f} ({self.calculated_at.strftime('%Y-%m-%d %H:%M')})"


class SafeInputRegexTemplate(models.Model):
    name = models.CharField(max_length=100, unique=True)
    pattern = models.CharField(max_length=500, unique=True)
    description = models.TextField()
    the_order = models.PositiveSmallIntegerField(default=0)
    enabled = models.BooleanField(default=True)

    # New secure masking fields
    keep_prefix_chars = models.PositiveSmallIntegerField(default=0,
                                                         help_text="Number of characters to keep visible at start")
    keep_prefix_digits = models.PositiveSmallIntegerField(default=0,
                                                          help_text="Number of digits to keep visible at start")
    hide_after_delimiter = models.CharField(max_length=10, blank=True, null=True,
                                            help_text="Delimiter to hide everything after (e.g., '@' for emails)")
    mask_type = models.CharField(
        max_length=20,
        choices=[
            ('prefix_only', 'Keep prefix only (most secure)'),
            ('prefix_suffix', 'Keep prefix and suffix (less secure)'),
            ('prefix_digits', 'Keep leading digits'),
            ('custom', 'Custom masking rules'),
        ],
        default='custom',
        help_text="Masking strategy to use"
    )

    class Meta:
        ordering = ['the_order', 'name']
