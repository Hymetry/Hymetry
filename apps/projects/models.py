import random
import secrets
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.text import slugify

from .domain_utils import normalize_workspace_website_url


WORKSPACE_SLUG_MAX_LENGTH = 40
WORKSPACE_SLUG_SUFFIX_DIGITS = 8
PROJECT_SLUG_MAX_LENGTH = 40
PROJECT_SLUG_SUFFIX_DIGITS = 8


def generate_unique_id():
    """Generates a unique 6 to 8-digit random number."""
    while True:
        # You can adjust the range to your needs
        potential_id = random.randint(100000, 99999999)
        if not Project.objects.filter(id=potential_id).exists():
            return potential_id


def generate_unique_workspace_public_id():
    """Generates a unique 8-digit workspace URL id."""
    while True:
        potential_id = random.randint(10000000, 99999999)
        if not Workspace.objects.filter(public_id=potential_id).exists():
            return potential_id


def workspace_slug_base(name):
    """Build a short, readable workspace slug from a workspace name."""
    raw_slug = slugify(name or '') or 'workspace'
    parts = [part for part in raw_slug.split('-') if part]
    if not parts:
        return 'workspace'

    slug = ''
    for part in parts:
        candidate = part if not slug else f'{slug}-{part}'
        if len(candidate) <= WORKSPACE_SLUG_MAX_LENGTH:
            slug = candidate
            continue
        if not slug:
            slug = part[:WORKSPACE_SLUG_MAX_LENGTH].strip('-')
        break

    return slug or 'workspace'


def workspace_slug_exists(slug, exclude_workspace_id=None):
    queryset = Workspace.objects.filter(Q(slug=slug) | Q(previous_slug=slug))
    if exclude_workspace_id:
        queryset = queryset.exclude(pk=exclude_workspace_id)
    return queryset.exists()


def generate_unique_workspace_slug(name, exclude_workspace_id=None):
    base_slug = workspace_slug_base(name)
    if not workspace_slug_exists(base_slug, exclude_workspace_id=exclude_workspace_id):
        return base_slug

    prefix_length = WORKSPACE_SLUG_MAX_LENGTH - WORKSPACE_SLUG_SUFFIX_DIGITS - 1
    prefix = base_slug[:prefix_length].strip('-') or 'workspace'
    while True:
        candidate = f'{prefix}-{random.randint(10 ** (WORKSPACE_SLUG_SUFFIX_DIGITS - 1), (10 ** WORKSPACE_SLUG_SUFFIX_DIGITS) - 1)}'
        if not workspace_slug_exists(candidate, exclude_workspace_id=exclude_workspace_id):
            return candidate


def project_slug_base(name):
    raw_slug = slugify(name or '') or 'project'
    parts = [part for part in raw_slug.split('-') if part]
    if not parts:
        return 'project'

    slug = ''
    for part in parts:
        candidate = part if not slug else f'{slug}-{part}'
        if len(candidate) <= PROJECT_SLUG_MAX_LENGTH:
            slug = candidate
            continue
        if not slug:
            slug = part[:PROJECT_SLUG_MAX_LENGTH].strip('-')
        break

    return slug or 'project'


def project_slug_exists(workspace_id, slug, exclude_project_id=None):
    if not workspace_id:
        return False
    queryset = Project.objects.filter(workspace_id=workspace_id, slug=slug)
    if exclude_project_id:
        queryset = queryset.exclude(pk=exclude_project_id)
    return queryset.exists()


def generate_unique_project_slug(name, workspace_id, exclude_project_id=None):
    base_slug = project_slug_base(name)
    if not project_slug_exists(workspace_id, base_slug, exclude_project_id=exclude_project_id):
        return base_slug

    prefix_length = PROJECT_SLUG_MAX_LENGTH - PROJECT_SLUG_SUFFIX_DIGITS - 1
    prefix = base_slug[:prefix_length].strip('-') or 'project'
    while True:
        candidate = f'{prefix}-{random.randint(10 ** (PROJECT_SLUG_SUFFIX_DIGITS - 1), (10 ** PROJECT_SLUG_SUFFIX_DIGITS) - 1)}'
        if not project_slug_exists(workspace_id, candidate, exclude_project_id=exclude_project_id):
            return candidate


class LifecycleStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    ARCHIVED = 'archived', 'Archived'


class ActiveLifecycleManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(lifecycle_status=LifecycleStatus.ACTIVE)


class ProjectActiveManager(ActiveLifecycleManager):
    def get_queryset(self):
        return super().get_queryset().filter(workspace__archived_at__isnull=True)


class WorkspaceActiveManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(archived_at__isnull=True)


class ProjectPageNamingState(models.TextChoices):
    NOT_STABLE = 'not_stable', 'Not stable'
    STABLE = 'stable', 'Stable'


class WorkspaceMemberRole(models.TextChoices):
    OWNER = 'owner', 'Owner'
    ADMIN = 'admin', 'Admin'
    MEMBER = 'member', 'Member'
    VIEWER = 'viewer', 'Viewer'


class WorkspaceMemberStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    REMOVED = 'removed', 'Removed'


class ProjectStatus(models.TextChoices):
    SETUP_REQUIRED = 'setup_required', 'Setup required'
    ACTIVE = 'active', 'Active'
    NO_RECENT_DATA = 'no_recent_data', 'No recent data'


class Workspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.PositiveBigIntegerField(
        unique=True,
        editable=False,
    )
    slug = models.SlugField(max_length=WORKSPACE_SLUG_MAX_LENGTH, unique=True, blank=True)
    previous_slug = models.SlugField(
        max_length=WORKSPACE_SLUG_MAX_LENGTH,
        unique=True,
        blank=True,
        null=True,
    )
    name = models.CharField(max_length=255)
    website_url = models.CharField(max_length=255, blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='created_workspaces',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    delete_after = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = models.Manager()
    active = WorkspaceActiveManager()

    class Meta:
        indexes = [
            models.Index(fields=['archived_at'], name='projects_workspace_arch_idx'),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.slug and self.previous_slug and self.slug == self.previous_slug:
            errors['previous_slug'] = 'Previous slug must be different from the current slug.'
        for field_name in ('slug', 'previous_slug'):
            value = getattr(self, field_name)
            if value and workspace_slug_exists(value, exclude_workspace_id=self.pk):
                errors[field_name] = 'Workspace slug must be unique across current and previous slugs.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.public_id:
            self.public_id = generate_unique_workspace_public_id()
        if not self.slug:
            self.slug = generate_unique_workspace_slug(self.name, exclude_workspace_id=self.pk)
        if self.previous_slug == '':
            self.previous_slug = None
        self.website_url = normalize_workspace_website_url(self.website_url)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Project(models.Model):
    id = models.PositiveBigIntegerField(primary_key=True, unique=True, editable=False)
    workspace = models.ForeignKey(Workspace, related_name='projects', on_delete=models.CASCADE)
    slug = models.SlugField(max_length=PROJECT_SLUG_MAX_LENGTH, blank=True)
    name = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='created_projects',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    api_key = models.CharField(max_length=64, unique=True, blank=True, null=True)
    product_url = models.CharField(max_length=500, blank=True, default='')
    allowed_domains = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=32,
        choices=ProjectStatus.choices,
        default=ProjectStatus.SETUP_REQUIRED,
    )
    first_production_event_at = models.DateTimeField(null=True, blank=True)
    last_event_at = models.DateTimeField(null=True, blank=True)
    timezone = models.CharField(max_length=50, default='UTC', help_text='Project timezone for session date filtering')
    tracking_capture = models.CharField(max_length=32, default='analytics,recording')
    page_structure_guidance = models.CharField(max_length=500, blank=True, default='')
    page_naming_state = models.CharField(
        max_length=16,
        choices=ProjectPageNamingState.choices,
        default=ProjectPageNamingState.NOT_STABLE,
    )
    page_naming_state_changed_at = models.DateTimeField(null=True, blank=True)
    page_naming_first_event_at = models.DateTimeField(null=True, blank=True)
    lifecycle_status = models.CharField(
        max_length=16,
        choices=LifecycleStatus.choices,
        default=LifecycleStatus.ACTIVE,
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    delete_after = models.DateTimeField(null=True, blank=True)

    objects = models.Manager()
    active = ProjectActiveManager()

    class Meta:
        indexes = [
            models.Index(fields=['workspace'], name='projects_workspace_idx'),
            models.Index(fields=['workspace', 'lifecycle_status'], name='projects_ws_lifecycle_idx'),
        ]
        constraints = [
            models.UniqueConstraint(fields=['workspace', 'slug'], name='projects_workspace_slug_unique'),
        ]

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = generate_unique_id()
        if not self.slug:
            self.slug = generate_unique_project_slug(self.name, self.workspace_id, exclude_project_id=self.pk)
        super().save(*args, **kwargs)

    def generate_api_key(self):
        self.api_key = secrets.token_hex(8).upper()
        self.save()

    def __str__(self):
        return self.name


class WorkspaceMembership(models.Model):
    workspace = models.ForeignKey(Workspace, related_name='memberships', on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='workspace_memberships', on_delete=models.CASCADE)
    role = models.CharField(max_length=16, choices=WorkspaceMemberRole.choices)
    status = models.CharField(
        max_length=16,
        choices=WorkspaceMemberStatus.choices,
        default=WorkspaceMemberStatus.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['workspace', 'user'], name='projects_workspace_user_unique'),
            models.CheckConstraint(
                condition=(
                    Q(status=WorkspaceMemberStatus.ACTIVE, removed_at__isnull=True)
                    | Q(status=WorkspaceMemberStatus.REMOVED, removed_at__isnull=False)
                ),
                name='projects_membership_status_removed_consistent',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'status', 'removed_at'], name='projects_member_user_state_idx'),
            models.Index(fields=['workspace', 'role', 'status'], name='projects_member_ws_role_idx'),
        ]

    @property
    def is_active(self):
        return self.status == WorkspaceMemberStatus.ACTIVE and self.removed_at is None

    def __str__(self):
        return f"{self.user} in {self.workspace}"


class WorkspaceOpenAIValidationStatus(models.TextChoices):
    UNCHECKED = 'unchecked', 'Not checked'
    VALID = 'valid', 'Valid'
    INVALID = 'invalid', 'Invalid'
    UNAVAILABLE = 'unavailable', 'Temporarily unavailable'


class WorkspaceOpenAICredential(models.Model):
    workspace = models.OneToOneField(
        Workspace,
        related_name='openai_credential',
        on_delete=models.CASCADE,
    )
    encrypted_api_key = models.TextField()
    key_last_four = models.CharField(max_length=4, blank=True, default='')
    validation_status = models.CharField(
        max_length=16,
        choices=WorkspaceOpenAIValidationStatus.choices,
        default=WorkspaceOpenAIValidationStatus.UNCHECKED,
    )
    validation_error_code = models.CharField(max_length=32, blank=True, default='')
    validated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='updated_workspace_openai_credentials',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def masked_key(self):
        return f'••••{self.key_last_four}' if self.key_last_four else 'Configured'

    def __str__(self):
        return f'OpenAI credential for {self.workspace}'
