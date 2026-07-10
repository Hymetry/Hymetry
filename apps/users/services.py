from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.models import InstallationState


class InitialAdminAlreadyConfigured(Exception):
    pass


def initial_admin_is_required():
    User = get_user_model()
    if User.objects.filter(is_superuser=True).exists():
        return False
    state = InstallationState.objects.filter(pk=1).only('admin_initialized_at').first()
    return not state or state.admin_initialized_at is None


@transaction.atomic
def create_initial_admin(*, email, password):
    normalized_email = str(email or '').strip().lower()
    if not normalized_email:
        raise ValidationError({'email': 'Enter an email address.'})
    validate_email(normalized_email)

    state, _ = InstallationState.objects.get_or_create(pk=1)
    state = InstallationState.objects.select_for_update().get(pk=state.pk)
    User = get_user_model()
    if state.admin_initialized_at is not None or User.objects.filter(is_superuser=True).exists():
        raise InitialAdminAlreadyConfigured('The initial administrator is already configured.')

    user = User(username=normalized_email, email=normalized_email, is_staff=True, is_superuser=True)
    validate_password(password, user)
    if User.objects.filter(username__iexact=normalized_email).exists():
        raise ValidationError({'email': 'A user with this email address already exists.'})
    user.set_password(password)
    user.save()

    state.admin_initialized_at = timezone.now()
    state.save(update_fields=['admin_initialized_at', 'updated_at'])
    return user
