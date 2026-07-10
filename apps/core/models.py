from django.db import models


class InstallationState(models.Model):
    singleton_id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    admin_initialized_at = models.DateTimeField(null=True, blank=True)
    seed_initialized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return 'Installation state'
