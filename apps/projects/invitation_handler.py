import re

from django.utils.crypto import get_random_string

from apps.projects.models import ProjectMembership, Invitation
from apps.projects.tasks import send_invitation_email


def is_celery_available():
    """
    Check if Celery is available and running
    """
    try:
        from celery import current_app
        # Try to inspect active workers
        inspect = current_app.control.inspect()
        active_workers = inspect.active()
        return active_workers is not None
    except Exception:
        return False


class InvitationHandler:
    """Handles email validation and invitation processing for team members"""

    def __init__(self, project, invited_by):
        self.project = project
        self.invited_by = invited_by
        self.email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

    def validate_emails(self, emails_text):
        """
        Validate email addresses and return validation results
        
        Args:
            emails_text (str): Raw text from textarea with emails (one per line)
            
        Returns:
            dict: Validation results with keys:
                - valid (bool): Whether validation passed
                - error (str): Error message if validation failed
                - warnings (list): List of warning messages
                - valid_count (int): Number of valid emails that can be invited
                - invalid_emails (list): List of invalid email addresses
                - already_invited (list): List of emails already invited
                - already_member (list): List of emails already members
        """
        if not emails_text.strip():
            return {
                'valid': False,
                'error': 'Please enter at least one email address.',
                'warnings': [],
                'valid_count': 0,
                'invalid_emails': [],
                'already_invited': [],
                'already_member': []
            }

        # Parse emails from textarea (one per line)
        emails = [email.strip() for email in emails_text.split('\n') if email.strip()]

        # Check max count first (before validating individual emails)
        if len(emails) > 10:
            return {
                'valid': False,
                'error': 'You can only invite up to 10 team members at once.',
                'warnings': [],
                'valid_count': 0,
                'invalid_emails': [],
                'already_invited': [],
                'already_member': []
            }

        # Validate email format
        invalid_emails = []
        valid_emails = []

        for email in emails:
            if not self.email_pattern.match(email):
                invalid_emails.append(email)
            else:
                valid_emails.append(email.lower())

        # Check for duplicates
        unique_emails = list(set(valid_emails))
        has_duplicates = len(unique_emails) != len(valid_emails)

        # Show errors if any invalid emails
        if invalid_emails:
            error_msg = f'Invalid email addresses: {", ".join(invalid_emails)}'
            return {
                'valid': False,
                'error': error_msg,
                'warnings': [],
                'valid_count': 0,
                'invalid_emails': invalid_emails,
                'already_invited': [],
                'already_member': []
            }

        if not unique_emails:
            return {
                'valid': False,
                'error': 'No valid email addresses provided.',
                'warnings': [],
                'valid_count': 0,
                'invalid_emails': invalid_emails,
                'already_invited': [],
                'already_member': []
            }

        # Check existing invitations and memberships
        already_invited = []
        already_member = []

        for email in unique_emails:
            # Check if user is already a member
            if ProjectMembership.objects.filter(project=self.project, user__email__iexact=email).exists():
                already_member.append(email)
                continue

            # Check if already invited
            if Invitation.objects.filter(project=self.project, email__iexact=email, active=False).exists():
                already_invited.append(email)
                continue

        # Build warnings
        warnings = []
        if already_invited:
            warnings.append(f'{len(already_invited)} email(s) already have pending invitations.')
        if already_member:
            warnings.append(f'{len(already_member)} email(s) are already team members.')
        if has_duplicates:
            warnings.append('Duplicate email addresses were removed.')

        valid_count = len(unique_emails) - len(already_invited) - len(already_member)

        return {
            'valid': True,
            'error': None,
            'warnings': warnings,
            'valid_count': valid_count,
            'invalid_emails': invalid_emails,
            'already_invited': already_invited,
            'already_member': already_member
        }

    def send_invitations(self, emails_text, request):
        """
        Queue Celery tasks to send invitations for valid email addresses
        
        Args:
            emails_text (str): Raw text from textarea with emails (one per line)
            request: Django request object (not used for Celery tasks)
            
        Returns:
            dict: Results with keys:
                - already_invited (int): Number already invited
                - already_member (int): Number already members
                - invalid_emails (list): List of invalid emails
                - celery_error (str): Error message if Celery is unavailable
                - validation_error (str): Error message if validation failed
        """
        # Validate emails first
        validation_result = self.validate_emails(emails_text)

        if not validation_result['valid']:
            return {
                'already_invited': 0,
                'already_member': 0,
                'invalid_emails': validation_result['invalid_emails'],
                'celery_error': None,
                'validation_error': validation_result['error']
            }

        # Only check Celery if emails are valid
        if not is_celery_available():
            return {
                'already_invited': 0,
                'already_member': 0,
                'invalid_emails': [],
                'celery_error': 'Email service is temporarily unavailable. Please try again later.',
                'validation_error': None
            }

        # Parse valid emails
        emails = [email.strip() for email in emails_text.split('\n') if email.strip()]
        valid_emails = []

        for email in emails:
            if self.email_pattern.match(email):
                valid_emails.append(email.lower())

        unique_emails = list(set(valid_emails))

        send_invitation_email.delay(unique_emails, self.project.id, self.invited_by.id)

        return {
            'already_invited': validation_result['already_invited'],
            'already_member': validation_result['already_member'],
            'invalid_emails': validation_result['invalid_emails'],
            'celery_error': None,
            'validation_error': None
        }

    def create_invitation(self, email):
        """
        Create invitation for a single email address
        
        Args:
            email (str): Email address to invite
            
        Returns:
            dict: Result with keys:
                - success (bool): Whether invitation was created and sent
                - reason (str): Reason if failed (already_member, already_invited, error)
        """
        try:
            # Check if user is already a member
            if ProjectMembership.objects.filter(project=self.project, user__email__iexact=email).exists():
                return {
                    'success': False,
                    'reason': 'already_member'
                }

            # Check if already invited
            existing_invitation = Invitation.objects.filter(
                project=self.project,
                email__iexact=email,
                active=False
            ).first()

            if existing_invitation:
                return {
                    'success': False,
                    'reason': 'already_invited'
                }

            # Create invitation
            token = get_random_string(64)
            invitation = Invitation.objects.create(
                email=email,
                project=self.project,
                invited_by=self.invited_by,
                token=token
            )

            # Build invitation URL
            from django.conf import settings
            from django.urls import reverse
            site_url = getattr(settings, 'SITE_URL', 'http://localhost').rstrip('/')
            invite_url = f"{site_url}{reverse('projects:accept_invitation', args=[token])}"

            # Prepare context for template
            context = {
                'project_name': self.project.name,
                'inviter_name': self.invited_by.get_full_name() or self.invited_by.username,
                'invite_url': invite_url,
            }

            # Render email templates
            from django.template.loader import render_to_string
            html_message = render_to_string('users/email/invitation_email.html', context)
            txt_subject = render_to_string('users/email/invitation_email_subject.txt', context)
            # Send email with both HTML and text versions
            from config.postmark import send_postmark_email
            send_postmark_email(
                subject=txt_subject,
                html_body=html_message,
                to=[email],
            )

            return {
                'success': True,
                'reason': 'invitation_sent'
            }

        except Exception as e:
            return {
                'success': False,
                'reason': f'error: {str(e)}'
            }

    def get_invitation_status(self, invitation):
        """
        Get the status of an invitation
        
        Args:
            invitation: Invitation object
            
        Returns:
            str: Status ('invited', 'expired', 'failed', 'accepted')
        """
        if invitation.active:
            return 'accepted'
        elif invitation.failed:
            return 'failed'
        elif invitation.is_expired():
            return 'expired'
        else:
            return 'invited'

    def can_resend_invitation(self, invitation):
        """
        Check if an invitation can be resent
        
        Args:
            invitation: Invitation object
            
        Returns:
            bool: True if invitation can be resent
        """
        return not invitation.active and not invitation.is_expired() and not invitation.failed

    def can_cancel_invitation(self, invitation):
        """
        Check if an invitation can be cancelled
        
        Args:
            invitation: Invitation object
            
        Returns:
            bool: True if invitation can be cancelled
        """
        return not invitation.active and not invitation.failed

    def can_remove_invitation(self, invitation):
        """
        Check if an invitation can be removed
        
        Args:
            invitation: Invitation object
            
        Returns:
            bool: True if invitation can be removed
        """
        return not invitation.active
