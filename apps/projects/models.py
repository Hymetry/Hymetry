import random
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


def generate_unique_id():
    """Generates a unique 6 to 8-digit random number."""
    while True:
        # You can adjust the range to your needs
        potential_id = random.randint(100000, 99999999)
        if not Project.objects.filter(id=potential_id).exists():
            return potential_id


class Project(models.Model):
    id = models.PositiveBigIntegerField(primary_key=True, unique=True, editable=False)
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='owned_projects', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    api_key = models.CharField(max_length=64, unique=True, blank=True, null=True)
    timezone = models.CharField(max_length=50, default='UTC', help_text='Project timezone for session date filtering')

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = generate_unique_id()
        super().save(*args, **kwargs)

    def generate_api_key(self):
        self.api_key = secrets.token_hex(8).upper()
        self.save()

    def __str__(self):
        return self.name


class ProjectMembership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    is_owner = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'project')

    def __str__(self):
        return f"{self.user} in {self.project}"

# Cloud version only
class Invitation(models.Model):
    email = models.EmailField()
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token = models.CharField(max_length=64, unique=True)
    active = models.BooleanField(default=False)
    failed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        expiration = getattr(settings, 'INVITATION_EXPIRATION_HOURS', 24)
        return (timezone.now() - self.created_at).total_seconds() > expiration * 3600

    def __str__(self):
        return f"Invite {self.email} to {self.project}"

# OSS version only - users who left their last project by themselves (1:1 with User)
class UserLeftLastProject(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='left_last_project_oss',
    )
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='users_who_left_oss')

    class Meta:
        db_table = 'projects_userleftlastproject'

    def __str__(self):
        return f"{self.user} left {self.project}"


# OSS version only
class ChatGptKeyManager(models.Manager):
    def update_check_fields(self, project_id, value):
        if project_id is None:
            return 0
        return self.filter(project_id=project_id).update(is_checked=True, check_result=value)

# OSS version only
class ChatGptKey(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    key = models.CharField(max_length=255)
    is_checked = models.BooleanField(default=False, help_text='True when validation has been run')
    check_result = models.BooleanField(null=True, help_text='True=valid, False=invalid. Meaningful when is_checked is True')

    objects = ChatGptKeyManager()

    def key_is_valid(self):
        from openai import OpenAI
        from apps.tracker.models import OpenAIModel

        client = OpenAI(api_key=str(self.key))
        try:
            openai_model = OpenAIModel.objects.filter(is_active=True).first()
            openai_model_name = 'gpt-4o' if openai_model is None else openai_model.name

            client.chat.completions.create(
                model=openai_model_name,
                messages=[{"role": "user", "content": "just tell me 'yes'"}]
            )
            return True
        except Exception:
            return False
