import random
import secrets
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.text import slugify

from .domain_utils import normalize_workspace_website_url
from .statuses import project_effective_status


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
    tracking_capture = models.CharField(max_length=32, default='analytics')
    page_structure_guidance = models.CharField(max_length=500, blank=True, default='')
    page_naming_state = models.CharField(
        max_length=16,
        choices=ProjectPageNamingState.choices,
        default=ProjectPageNamingState.NOT_STABLE,
    )
    page_naming_state_changed_at = models.DateTimeField(null=True, blank=True)
    page_naming_first_event_at = models.DateTimeField(null=True, blank=True)
    filtered_analytics_revision = models.PositiveBigIntegerField(default=0)
    analytics_facts_revision = models.PositiveBigIntegerField(default=0)
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

    @property
    def effective_status(self):
        return project_effective_status(self)

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


class CompanyAttributeType(models.TextChoices):
    TEXT = 'text', 'Text'
    NUMBER = 'number', 'Number'
    MONEY = 'money', 'Money'
    DATE = 'date', 'Date'
    BOOLEAN = 'boolean', 'Boolean'
    SINGLE_SELECT = 'single_select', 'Single select'


class CompanyAttributeNumberFormat(models.TextChoices):
    PLAIN = 'plain', 'Plain number'
    PERCENTAGE = 'percentage', 'Percentage'


class CompanyAttributeMoneyCurrency(models.TextChoices):
    USD = 'USD', 'USD'
    EUR = 'EUR', 'EUR'
    GBP = 'GBP', 'GBP'
    AED = 'AED', 'AED'
    AUD = 'AUD', 'AUD'
    BGN = 'BGN', 'BGN'
    BRL = 'BRL', 'BRL'
    CAD = 'CAD', 'CAD'
    CHF = 'CHF', 'CHF'
    CNY = 'CNY', 'CNY'
    CZK = 'CZK', 'CZK'
    DKK = 'DKK', 'DKK'
    HKD = 'HKD', 'HKD'
    HUF = 'HUF', 'HUF'
    ILS = 'ILS', 'ILS'
    INR = 'INR', 'INR'
    JPY = 'JPY', 'JPY'
    KRW = 'KRW', 'KRW'
    MXN = 'MXN', 'MXN'
    NOK = 'NOK', 'NOK'
    NZD = 'NZD', 'NZD'
    PLN = 'PLN', 'PLN'
    RON = 'RON', 'RON'
    SAR = 'SAR', 'SAR'
    SEK = 'SEK', 'SEK'
    SGD = 'SGD', 'SGD'
    TRY = 'TRY', 'TRY'
    UAH = 'UAH', 'UAH'
    ZAR = 'ZAR', 'ZAR'


class CompanyAttributeMoneyDisplay(models.TextChoices):
    COMPACT = 'compact', 'Compact'
    FULL = 'full', 'Full'


class CompanyAttributeBooleanDisplay(models.TextChoices):
    YES_NO = 'yes_no', 'Yes / No'
    CHECKMARK_DASH = 'checkmark_dash', 'Checkmark / Dash'


class CompanyAttributeOptionColor(models.TextChoices):
    RED = 'red', 'Red'
    ORANGE = 'orange', 'Orange'
    AMBER = 'amber', 'Amber'
    YELLOW = 'yellow', 'Yellow'
    LIME = 'lime', 'Lime'
    GREEN = 'green', 'Green'
    EMERALD = 'emerald', 'Emerald'
    TEAL = 'teal', 'Teal'
    CYAN = 'cyan', 'Cyan'
    SKY = 'sky', 'Sky'
    BLUE = 'blue', 'Blue'
    INDIGO = 'indigo', 'Indigo'
    VIOLET = 'violet', 'Violet'
    PURPLE = 'purple', 'Purple'
    PINK = 'pink', 'Pink'
    SLATE = 'slate', 'Slate'


# These are the exact presets offered by the company-attribute editor. Keeping a
# token in the database prevents arbitrary user-supplied CSS colors from being
# rendered later.
COMPANY_ATTRIBUTE_OPTION_COLOR_PALETTE = {
    CompanyAttributeOptionColor.RED: {'text': '#B91C1C', 'bg': '#FEE2E2', 'border': '#FECACA'},
    CompanyAttributeOptionColor.ORANGE: {'text': '#C2410C', 'bg': '#FFEDD5', 'border': '#FED7AA'},
    CompanyAttributeOptionColor.AMBER: {'text': '#B45309', 'bg': '#FEF3C7', 'border': '#FDE68A'},
    CompanyAttributeOptionColor.YELLOW: {'text': '#A16207', 'bg': '#FEF9C3', 'border': '#FEF08A'},
    CompanyAttributeOptionColor.LIME: {'text': '#4D7C0F', 'bg': '#ECFCCB', 'border': '#D9F99D'},
    CompanyAttributeOptionColor.GREEN: {'text': '#15803D', 'bg': '#DCFCE7', 'border': '#BBF7D0'},
    CompanyAttributeOptionColor.EMERALD: {'text': '#047857', 'bg': '#D1FAE5', 'border': '#A7F3D0'},
    CompanyAttributeOptionColor.TEAL: {'text': '#0F766E', 'bg': '#CCFBF1', 'border': '#99F6E4'},
    CompanyAttributeOptionColor.CYAN: {'text': '#0E7490', 'bg': '#CFFAFE', 'border': '#A5F3FC'},
    CompanyAttributeOptionColor.SKY: {'text': '#0369A1', 'bg': '#E0F2FE', 'border': '#BAE6FD'},
    CompanyAttributeOptionColor.BLUE: {'text': '#1D4ED8', 'bg': '#DBEAFE', 'border': '#BFDBFE'},
    CompanyAttributeOptionColor.INDIGO: {'text': '#4338CA', 'bg': '#E0E7FF', 'border': '#C7D2FE'},
    CompanyAttributeOptionColor.VIOLET: {'text': '#6D28D9', 'bg': '#EDE9FE', 'border': '#DDD6FE'},
    CompanyAttributeOptionColor.PURPLE: {'text': '#7E22CE', 'bg': '#F3E8FF', 'border': '#E9D5FF'},
    CompanyAttributeOptionColor.PINK: {'text': '#BE185D', 'bg': '#FCE7F3', 'border': '#FBCFE8'},
    CompanyAttributeOptionColor.SLATE: {'text': '#334155', 'bg': '#F1F5F9', 'border': '#E2E8F0'},
}


class CompanyAttribute(models.Model):
    project = models.ForeignKey(Project, related_name='company_attributes', on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    attribute_type = models.CharField(max_length=20, choices=CompanyAttributeType.choices)
    position = models.PositiveIntegerField(default=0)
    number_format = models.CharField(
        max_length=16,
        choices=CompanyAttributeNumberFormat.choices,
        blank=True,
        default='',
    )
    decimal_places = models.PositiveSmallIntegerField(null=True, blank=True)
    currency = models.CharField(
        max_length=3,
        choices=CompanyAttributeMoneyCurrency.choices,
        blank=True,
        default='',
    )
    money_display = models.CharField(
        max_length=16,
        choices=CompanyAttributeMoneyDisplay.choices,
        blank=True,
        default='',
    )
    boolean_display = models.CharField(
        max_length=24,
        choices=CompanyAttributeBooleanDisplay.choices,
        blank=True,
        default='',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['position', 'id']
        constraints = [
            models.UniqueConstraint(
                Lower('name'),
                'project',
                name='projects_attr_project_name_ci_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['project', 'position'], name='projects_attr_proj_pos_idx'),
        ]

    def clean(self):
        super().clean()
        self.name = (self.name or '').strip()
        errors = {}

        if not self.name:
            errors['name'] = 'Enter an attribute name.'

        if self.pk:
            original_type = type(self).objects.filter(pk=self.pk).values_list('attribute_type', flat=True).first()
            if original_type and original_type != self.attribute_type:
                errors['attribute_type'] = 'Attribute type cannot be changed after creation.'

        if self.attribute_type == CompanyAttributeType.NUMBER:
            if self.number_format not in CompanyAttributeNumberFormat.values:
                errors['number_format'] = 'Select a valid number format.'
            if self.decimal_places not in (0, 1, 2):
                errors['decimal_places'] = 'Decimal places must be 0, 1, or 2.'
        elif self.number_format or self.decimal_places is not None:
            errors['number_format'] = 'Number settings are only valid for number attributes.'

        if self.attribute_type == CompanyAttributeType.MONEY:
            if self.currency not in CompanyAttributeMoneyCurrency.values:
                errors['currency'] = 'Select a valid currency.'
            if self.money_display not in CompanyAttributeMoneyDisplay.values:
                errors['money_display'] = 'Select a valid money display format.'
        elif self.currency or self.money_display:
            errors['currency'] = 'Money settings are only valid for money attributes.'

        if self.attribute_type == CompanyAttributeType.BOOLEAN:
            if self.boolean_display not in CompanyAttributeBooleanDisplay.values:
                errors['boolean_display'] = 'Select a valid boolean display style.'
        elif self.boolean_display:
            errors['boolean_display'] = 'Boolean settings are only valid for boolean attributes.'

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.project_id}: {self.name}'


class CompanyAttributeOption(models.Model):
    attribute = models.ForeignKey(CompanyAttribute, related_name='options', on_delete=models.CASCADE)
    label = models.CharField(max_length=100)
    color = models.CharField(
        max_length=16,
        choices=CompanyAttributeOptionColor.choices,
        default=CompanyAttributeOptionColor.CYAN,
    )
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['position', 'id']
        constraints = [
            models.UniqueConstraint(
                Lower('label'),
                'attribute',
                name='projects_attr_option_label_ci_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['attribute', 'position'], name='projects_opt_attr_pos_idx'),
        ]

    def clean(self):
        super().clean()
        self.label = (self.label or '').strip()
        errors = {}
        if not self.label:
            errors['label'] = 'Enter an option label.'
        if self.attribute_id:
            attribute_type = (
                self.attribute.attribute_type
                if 'attribute' in self._state.fields_cache
                else CompanyAttribute.objects.filter(pk=self.attribute_id).values_list('attribute_type', flat=True).first()
            )
            if attribute_type and attribute_type != CompanyAttributeType.SINGLE_SELECT:
                errors['attribute'] = 'Options are only valid for single-select attributes.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.label


class CompanyAttributeValue(models.Model):
    attribute = models.ForeignKey(CompanyAttribute, related_name='values', on_delete=models.CASCADE)
    company_id = models.CharField(max_length=255)
    text_value = models.TextField(null=True, blank=True)
    decimal_value = models.DecimalField(max_digits=30, decimal_places=10, null=True, blank=True)
    date_value = models.DateField(null=True, blank=True)
    boolean_value = models.BooleanField(null=True, blank=True)
    option = models.ForeignKey(
        CompanyAttributeOption,
        related_name='values',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['attribute', 'company_id'],
                name='projects_attr_value_company_uniq',
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        text_value__isnull=False,
                        decimal_value__isnull=True,
                        date_value__isnull=True,
                        boolean_value__isnull=True,
                        option__isnull=True,
                    )
                    | Q(
                        text_value__isnull=True,
                        decimal_value__isnull=False,
                        date_value__isnull=True,
                        boolean_value__isnull=True,
                        option__isnull=True,
                    )
                    | Q(
                        text_value__isnull=True,
                        decimal_value__isnull=True,
                        date_value__isnull=False,
                        boolean_value__isnull=True,
                        option__isnull=True,
                    )
                    | Q(
                        text_value__isnull=True,
                        decimal_value__isnull=True,
                        date_value__isnull=True,
                        boolean_value__isnull=False,
                        option__isnull=True,
                    )
                    | Q(
                        text_value__isnull=True,
                        decimal_value__isnull=True,
                        date_value__isnull=True,
                        boolean_value__isnull=True,
                        option__isnull=False,
                    )
                ),
                name='projects_attr_value_one_typed',
            ),
        ]
        indexes = [
            models.Index(fields=['company_id'], name='projects_attrval_company_idx'),
            models.Index(fields=['attribute', 'decimal_value'], name='projects_attrval_decimal_idx'),
            models.Index(fields=['attribute', 'date_value'], name='projects_attrval_date_idx'),
            models.Index(fields=['attribute', 'boolean_value'], name='projects_attrval_bool_idx'),
            models.Index(fields=['attribute', 'option'], name='projects_attrval_option_idx'),
        ]

    def clean(self):
        super().clean()
        self.company_id = (self.company_id or '').strip()
        errors = {}
        if not self.company_id:
            errors['company_id'] = 'Company ID is required.'

        populated = {
            'text': self.text_value is not None and self.text_value != '',
            'decimal': self.decimal_value is not None,
            'date': self.date_value is not None,
            'boolean': self.boolean_value is not None,
            'option': self.option_id is not None,
        }
        if sum(populated.values()) != 1:
            errors['value'] = 'Exactly one typed value must be set.'
        elif self.attribute_id:
            attribute_type = (
                self.attribute.attribute_type
                if 'attribute' in self._state.fields_cache
                else CompanyAttribute.objects.filter(pk=self.attribute_id).values_list('attribute_type', flat=True).first()
            )
            expected_field = {
                CompanyAttributeType.TEXT: 'text',
                CompanyAttributeType.NUMBER: 'decimal',
                CompanyAttributeType.MONEY: 'decimal',
                CompanyAttributeType.DATE: 'date',
                CompanyAttributeType.BOOLEAN: 'boolean',
                CompanyAttributeType.SINGLE_SELECT: 'option',
            }.get(attribute_type)
            if expected_field and not populated[expected_field]:
                errors['value'] = f'Value does not match the {attribute_type} attribute type.'

        if self.option_id:
            option_attribute_id = (
                self.option.attribute_id
                if 'option' in self._state.fields_cache
                else CompanyAttributeOption.objects.filter(pk=self.option_id).values_list('attribute_id', flat=True).first()
            )
            if option_attribute_id != self.attribute_id:
                errors['option'] = 'Select an option that belongs to this attribute.'

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.company_id}: {self.attribute.name}'


class CompanySegment(models.Model):
    """A named, reusable company-attribute filter definition owned by one user.

    ``definition`` holds the same serialized shape the filter dialog and the
    ``ca.*`` URL state already use, so a segment never introduces a second
    filter format: ``{"<attribute_id>": {"op": ..., "value(s)"/"min"/"max"/
    "from"/"to": ...}}``.

    A null ``user`` marks a *seeded* segment: a curated definition that belongs
    to the project rather than to a person, so the read-only demo can offer it
    to anonymous visitors. Seeded segments are written by
    ``seed_demo_company_segments`` and never appear in a signed-in user's own
    list.

    ``needs_review`` marks a segment whose definition still names an attribute
    somebody deleted. The definition is left exactly as it was written — a
    segment is never silently rewritten or renamed — so
    ``pending_attribute_deletions`` carries what the owner has to be told about
    the deletion: the attribute name, who deleted it, and when. Both are cleared
    together once the owner saves a definition that no longer references them.
    """

    project = models.ForeignKey(Project, related_name='company_segments', on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='company_segments',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    name = models.CharField(max_length=100)
    definition = models.JSONField(default=dict)
    needs_review = models.BooleanField(default=False)
    pending_attribute_deletions = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'id']
        constraints = [
            # Segments are personal, so uniqueness is scoped to the owner rather
            # than to the whole project.
            models.UniqueConstraint(
                Lower('name'),
                'project',
                'user',
                name='projects_segment_owner_name_ci_uniq',
            ),
            # Null owners compare as distinct, so seeded segments need their own
            # per-project uniqueness rather than relying on the owner constraint.
            models.UniqueConstraint(
                Lower('name'),
                'project',
                condition=models.Q(user__isnull=True),
                name='projects_segment_seeded_name_ci_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['project', 'user', 'name'], name='projects_segment_owner_idx'),
            # Every analytics page asks whether the viewer owns a segment waiting
            # for review, so that question stays a single indexed lookup.
            models.Index(
                fields=['project', 'user', 'needs_review'],
                name='projects_segment_review_idx',
            ),
        ]

    @property
    def is_seeded(self):
        return self.user_id is None

    def clean(self):
        super().clean()
        self.name = (self.name or '').strip()
        errors = {}
        if not self.name:
            errors['name'] = 'Enter a segment name.'
        if not isinstance(self.definition, dict) or not self.definition:
            errors['definition'] = 'Add at least one company attribute condition.'
        if not isinstance(self.pending_attribute_deletions, list):
            errors['pending_attribute_deletions'] = 'Deleted attribute records must be a list.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.project_id}: {self.name}'


class AnalyticsFilterState(models.Model):
    """The filters one person last applied across a whole project.

    Some answers belong to the project rather than to any one screen. "Which
    companies am I looking at" and "over what period" are the same question on
    Pages, Companies, Users, and Visits, so they are remembered once per user
    and project and restored on all of them.

    ``definition`` holds the company-attribute scope in the same serialized
    shape the filter dialog, the ``ca.*`` URL state, and
    ``CompanySegment.definition`` already use, so restoring never introduces a
    second filter format. ``segment`` records that the scope was a named segment
    rather than an unsaved custom filter, and clears itself when that segment is
    deleted. The definition survives that deletion on purpose: the editor turns
    the active scope of a deleted segment into the same conditions under the
    "Custom filter" label, and a restored scope should say exactly what the page
    said.

    ``state`` carries the remaining project-level filters — today the selected
    period — in the same parameter-to-values shape as ``AnalyticsPageState``.

    Only committed state is written. A draft still being edited in the dialog
    has not been applied to anything and never reaches this table.
    """

    project = models.ForeignKey(
        Project,
        related_name='analytics_filter_states',
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='analytics_filter_states',
        on_delete=models.CASCADE,
    )
    definition = models.JSONField(default=dict, blank=True)
    segment = models.ForeignKey(
        CompanySegment,
        related_name='filter_states',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    state = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'user'],
                name='projects_analytics_filter_state_uniq',
            ),
        ]

    def __str__(self):
        return f'{self.project_id}: analytics filters for {self.user_id}'


class AnalyticsPageState(models.Model):
    """The filters one person last applied on one analytical page.

    ``page_key`` is a stable identifier for the page itself, never a route or a
    label, so renaming a URL does not orphan what somebody saved. Filters that
    belong to a single page are stored under that page's key alone: a Visits
    page filter says nothing about Companies, so nothing is ever copied between
    pages. Filters every page shares live in ``AnalyticsFilterState`` instead.

    ``state`` maps a query parameter name to the values the page resolved and
    applied, always as a list of strings holding stable identifiers rather than
    labels. Values whose target no longer exists are dropped when the state is
    read, so a deleted product area or page rule simply stops coming back.
    """

    PAGE_KEY_MAX_LENGTH = 64

    project = models.ForeignKey(
        Project,
        related_name='analytics_page_states',
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='analytics_page_states',
        on_delete=models.CASCADE,
    )
    page_key = models.CharField(max_length=PAGE_KEY_MAX_LENGTH)
    state = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'user', 'page_key'],
                name='projects_analytics_page_state_uniq',
            ),
        ]

    def __str__(self):
        return f'{self.project_id}: {self.page_key} filters for {self.user_id}'


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
