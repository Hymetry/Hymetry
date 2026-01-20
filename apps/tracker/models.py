import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.projects.models import Project


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


class Page(models.Model):
    url = models.URLField(unique=True)
    original_title = models.CharField(max_length=255, verbose_name="Original title", default="")

    _title = models.CharField(
        max_length=255,
        verbose_name="AI generated title",
        blank=True,
        default="",
        db_column="title"  # Keeps DB column unchanged
    )

    created_at = models.DateTimeField(default=timezone.now)
    color_index = models.PositiveSmallIntegerField(default=1)

    def __str__(self):
        return f"{self.title} ({self.url})"

    @property
    def title(self):
        return self._title or self.original_title

    @title.setter
    def title(self, value):
        self._title = value


class Event(models.Model):
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='events')
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='events', null=True)
    tab_id = models.CharField(max_length=36, help_text="Unique browser tab identifier", null=True)
    event_type = models.PositiveSmallIntegerField()
    timestamp = models.DateTimeField(default=timezone.now)
    data = models.JSONField()

    def __str__(self):
        return f"{self.event_type} at {self.timestamp}"


class OpenAIModel(models.Model):
    MODEL_SUGGESTIONS = ['gpt-4o', 'gpt-4o-mini', 'gpt-4', 'gpt-3.5-turbo']

    name = models.CharField(
        max_length=50,
        unique=True,
        help_text=f"Suggested values: {', '.join(MODEL_SUGGESTIONS)}"
    )
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if self.is_active:
            OpenAIModel.objects.filter(~Q(id=self.id), is_active=True).update(is_active=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} {'(active)' if self.is_active else ''}"


class TitlePrompt(models.Model):
    name = models.CharField(max_length=100, unique=True)
    prompt_text = models.TextField()
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if self.is_active:
            TitlePrompt.objects.filter(~Q(id=self.id), is_active=True).update(is_active=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name}{' (active)' if self.is_active else ''}"


class BubbleCache(models.Model):
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='bubbles')
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='bubbles', null=True)
    timestamp = models.DateTimeField(verbose_name="Hour and Minute")
    size = models.PositiveSmallIntegerField(verbose_name="Bubble size")
    clicks = models.PositiveSmallIntegerField(verbose_name="Click count")
    mouse_moves = models.PositiveSmallIntegerField(verbose_name="Mouse movements")
    key_strokes = models.PositiveSmallIntegerField(verbose_name="Key strokes")
    seconds_spent = models.PositiveIntegerField(verbose_name="Seconds spent on page", default=0)

    def __str__(self):
        return f"{self.page}, {self.size}"


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
    keep_prefix_chars = models.PositiveSmallIntegerField(default=0, help_text="Number of characters to keep visible at start")
    keep_prefix_digits = models.PositiveSmallIntegerField(default=0, help_text="Number of digits to keep visible at start")
    hide_after_delimiter = models.CharField(max_length=10, blank=True, null=True, help_text="Delimiter to hide everything after (e.g., '@' for emails)")
    mask_type = models.CharField(
        max_length=20,
        choices=[
            ('prefix_only', 'Keep prefix only (most secure)'),
            ('prefix_suffix', 'Keep prefix and suffix (less secure)'),
        ],
        default='custom',
        help_text="Masking strategy to use"
    )

    class Meta:
        ordering = ['the_order', 'name']


