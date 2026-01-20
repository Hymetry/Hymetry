from allauth.account.signals import email_confirmed
from django.contrib.auth import login
from django.dispatch import receiver


@receiver(email_confirmed)
def handle_email_confirmation(sender, request, email_address, **kwargs):
    """Handle email confirmation and automatically log in the user"""
    user = email_address.user
    if not request.user.is_authenticated:
        # Automatically log in the user with the allauth backend
        login(request, user, backend='allauth.account.auth_backends.AuthenticationBackend')
