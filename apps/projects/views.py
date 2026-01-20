from zoneinfo import ZoneInfo, available_timezones

from allauth.account.signals import user_logged_in
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.dispatch import receiver
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string

from apps.tracker.models import Event
from apps.users.forms import ProjectForm, InvitationForm
from config.postmark import send_postmark_email
from .decorators import require_project_member, require_project_owner
from .invitation_handler import InvitationHandler
from .models import Project, ProjectMembership, Invitation
from .utils import generate_tracking_script


class InvitationForm(forms.Form):
    email = forms.EmailField()


@login_required
def project_list(request):
    """View for the modern all projects page"""
    memberships = ProjectMembership.objects.filter(user=request.user).select_related('project')
    return render(request, 'projects/project_list.html', {'memberships': memberships})


@login_required
def project_create(request):
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save(commit=False)
            project.owner = request.user

            # Set timezone from form data if provided
            timezone_value = request.POST.get('timezone', 'UTC')

            # Validate timezone using zoneinfo
            try:
                ZoneInfo(timezone_value)  # This will raise an exception if timezone is invalid
                project.timezone = timezone_value
            except Exception:
                project.timezone = 'UTC'  # Fallback to UTC if invalid

            project.save()
            ProjectMembership.objects.create(user=request.user, project=project, is_owner=True)
            project.generate_api_key()
            return redirect('projects:project_settings', project_id=project.id)
    else:
        form = ProjectForm()
    return render(request, 'projects/project_form.html', {'form': form})


@login_required
def project_delete(request, pk):
    project = get_object_or_404(Project, pk=pk, owner=request.user)
    if request.method == 'POST':
        project.delete()
        return redirect('projects:project_list')
    return render(request, 'projects/project_confirm_delete.html', {'project': project})


@login_required
@require_project_member
def invite_user(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    # Allow any member to invite
    if request.method == 'POST':
        form = InvitationForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            # Prevent inviting the owner
            if email.lower() == project.owner.email.lower():
                return render(request, 'projects/invite_user.html', {'form': form, 'project': project})
            token = get_random_string(64)
            # Check for existing pending invitation
            invitation = Invitation.objects.filter(email=email, project=project, active=False).first()
            if invitation:
                invitation.token = token
                invitation.invited_by = request.user
                invitation.created_at = timezone.now()
                invitation.save()
            else:
                Invitation.objects.create(
                    email=email, project=project, invited_by=request.user, token=token
                )
            invite_url = request.build_absolute_uri(
                reverse('projects:accept_invitation', args=[token])
            )
            send_postmark_email(
                subject='You are invited!',
                html_body=f'Join the project: {invite_url}',
                to=[email]
            )
            return redirect('project_detail', project_id=project_id)
    else:
        form = InvitationForm()
    return render(request, 'projects/invite_user.html', {'form': form, 'project': project})


def accept_invitation(request, token):
    """Handle invitation acceptance and redirect to accept page"""
    invitation = get_object_or_404(Invitation, token=token)

    # If invitation is already accepted, check if user is authenticated
    if invitation.active:
        # Check if user with this email exists and authenticate them
        User = get_user_model()
        try:
            user = User.objects.get(email__iexact=invitation.email)
            # Auto-authenticate the user
            from django.contrib.auth import login
            from django.contrib.auth.backends import ModelBackend
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        except User.DoesNotExist:
            # User doesn't exist, redirect to create account
            return redirect('projects:invitation_create_account', token=invitation.token)
        except User.MultipleObjectsReturned:
            # Multiple users with same email - redirect to create account with error
            return redirect('projects:invitation_create_account', token=invitation.token)

        return redirect('projects:project_intro', project_id=invitation.project.pk)

    if invitation.is_expired():
        return redirect('projects:project_list')

    # Store invitation token in session for the accept page
    request.session['pending_invitation_token'] = invitation.token
    # Redirect to the accept page
    return redirect('projects:invitation_accept', token=invitation.token)


def invitation_accept(request, token):
    """Display the invitation accept page"""
    invitation = get_object_or_404(Invitation, token=token)

    # If invitation is already accepted, redirect to project settings
    if invitation.active:
        return redirect('projects:project_intro', project_id=invitation.project.pk)

    if invitation.is_expired():
        return redirect('projects:project_list')

    # Check if user with this email exists and auto-login them
    User = get_user_model()
    try:
        user = User.objects.get(email__iexact=invitation.email)
        # Auto-authenticate the user
        from django.contrib.auth import login
        from django.contrib.auth.backends import ModelBackend
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    except User.DoesNotExist:
        # User doesn't exist - show create account page
        context = {
            'invitation': invitation,
            'project': invitation.project,
            'inviter_name': invitation.invited_by.get_full_name() or invitation.invited_by.username,
        }
        return render(request, 'projects/invitation_create_account.html', context)
    except User.MultipleObjectsReturned:
        # Multiple users with same email - show error page
        context = {
            'invitation': invitation,
            'project': invitation.project,
            'inviter_name': invitation.invited_by.get_full_name() or invitation.invited_by.username,
            'error_message': 'Multiple accounts found with this email address. Please contact support for assistance.',
        }
        return render(request, 'projects/invitation_create_account.html', context)

    # User exists and is now authenticated - show accept page
    context = {
        'invitation': invitation,
        'project': invitation.project,
        'inviter_name': invitation.invited_by.get_full_name() or invitation.invited_by.username,
    }
    return render(request, 'projects/invitation_accept.html', context)


@login_required
def remove_active_user(request, project_id, membership_id):
    project = get_object_or_404(Project, pk=project_id)

    try:
        membership = get_object_or_404(ProjectMembership, id=membership_id, project=project)
    except:
        return redirect('projects:project_settings', project_id=project_id)

    # Check if trying to remove the owner
    if membership.is_owner:
        return redirect('projects:project_settings', project_id=project_id)

    if request.user != project.owner and request.user != membership.user:
        return redirect('projects:project_settings', project_id=project_id)

    if request.user == membership.user and request.user != project.owner:
        # User can only remove themselves
        membership.delete()
        return redirect('projects:project_list')
    elif request.user == project.owner:
        membership.delete()
        return redirect('projects:project_settings', project_id=project_id)
    else:
        return redirect('projects:project_settings', project_id=project_id)


@login_required
def remove_invitation(request, project_id, token):
    project = get_object_or_404(Project, pk=project_id)
    invitation = get_object_or_404(Invitation, token=token, project=project, active=False)
    # Allow project owner or the inviter to cancel
    if request.user != project.owner and request.user != invitation.invited_by:
        return redirect('projects:project_settings', project_id=project_id)
    invitation.delete()
    return redirect('projects:project_settings', project_id=project_id)


@login_required
def resend_invitation(request, project_id, token):
    """Resend an invitation to a user"""
    project = get_object_or_404(Project, pk=project_id)
    invitation = get_object_or_404(Invitation, token=token, project=project, active=False)

    # Allow project owner or the inviter to resend
    if request.user != project.owner and request.user != invitation.invited_by:
        return redirect('projects:project_settings', project_id=project_id)

    # Check if invitation is expired
    if invitation.is_expired():
        return redirect('projects:project_settings', project_id=project_id)

    # Generate new token and update invitation
    token = get_random_string(64)
    invitation.token = token
    invitation.created_at = timezone.now()
    invitation.failed = False
    invitation.save()

    # Send new invitation email using templates
    invite_url = request.build_absolute_uri(
        reverse('projects:accept_invitation', args=[token])
    )

    # Prepare context for template
    context = {
        'project_name': project.name,
        'inviter_name': invitation.invited_by.get_full_name() or invitation.invited_by.username,
        'invite_url': invite_url,
    }

    # Render email templates
    html_message = render_to_string('users/email/invitation_email.html', context)
    txt_subject = render_to_string('users/email/invitation_email_subject.txt', context)
    # Send email with both HTML and text versions
    send_postmark_email(
        subject=txt_subject,
        to=[invitation.email],
        html_body=html_message,
    )
    return redirect('projects:project_settings', project_id=project_id)


@login_required
def cancel_invitation(request, project_id, token):
    """Cancel an invitation (mark as failed)"""
    project = get_object_or_404(Project, pk=project_id)
    invitation = get_object_or_404(Invitation, token=token, project=project, active=False)

    # Only project owner can cancel invitations
    if request.user != project.owner:
        return redirect('projects:project_settings', project_id=project_id)

    # Mark invitation as failed (cancelled)
    invitation.failed = True
    invitation.save()

    return redirect('projects:project_settings', project_id=project_id)


# After login, check for pending invitation in session and auto-accept
@receiver(user_logged_in)
def handle_pending_invitation(sender, request, user, **kwargs):
    token = request.session.get('pending_invitation_token')
    if token:
        try:
            invitation = Invitation.objects.get(token=token, active=False)
            if invitation.is_expired():
                del request.session['pending_invitation_token']
                return
            # Only accept if the logged-in user's email matches the invitation
            if user.email.lower() == invitation.email.lower():
                # Auto-verify the email address since they confirmed the invitation
                from allauth.account.models import EmailAddress
                email_address, created = EmailAddress.objects.get_or_create(
                    user=user,
                    email=user.email,
                    defaults={'verified': True, 'primary': True}
                )
                if not created:
                    # If email address already exists, mark it as verified
                    email_address.verified = True
                    email_address.primary = True
                    email_address.save()

                already_member = ProjectMembership.objects.filter(user=user, project=invitation.project).exists()
                already_active = Invitation.objects.filter(project=invitation.project, email=invitation.email,
                                                           active=True).exists()
                if not already_member:
                    ProjectMembership.objects.get_or_create(
                        user=user, project=invitation.project, defaults={'is_owner': False}
                    )
                # Mark this invitation as accepted and clean up other pending invitations
                invitation.active = True
                invitation.save()
                # Clean up other pending invitations for the same email
                Invitation.objects.filter(
                    project=invitation.project,
                    email=invitation.email,
                    active=False
                ).exclude(id=invitation.id).delete()
                del request.session['pending_invitation_token']
                request._pending_invitation_redirect = True
            else:
                # Mark as failed if wrong user
                invitation.failed = True
                invitation.save()
                del request.session['pending_invitation_token']
        except Invitation.DoesNotExist:
            pass


@login_required
@require_project_owner
def update_project_name(request, project_id):
    """Handle project name updates"""
    project = get_object_or_404(Project, pk=project_id)

    if request.method == 'POST':
        new_name = request.POST.get('name', '').strip()

        if new_name:
            project.name = new_name
            project.save()
            return JsonResponse({'success': True, 'new_name': new_name})
        else:
            return JsonResponse({'success': False, 'error': 'Project name cannot be empty.'})

    return JsonResponse({'success': False, 'error': 'Invalid request method.'})


@login_required
@require_project_owner
def update_project_timezone(request, project_id):
    """Handle project timezone change"""
    if request.method == 'POST':
        project = get_object_or_404(Project, pk=project_id, owner=request.user)
        new_timezone = request.POST.get('timezone', '').strip()

        # Validate timezone using zoneinfo
        try:
            ZoneInfo(new_timezone)  # This will raise an exception if timezone is invalid
            project.timezone = new_timezone
            project.save()
            return redirect('projects:project_settings', project_id=project.id)
        except Exception:
            return JsonResponse({'success': False, 'error': 'Invalid timezone.'})

    return JsonResponse({'success': False, 'error': 'Invalid request method.'})


@login_required
@require_project_member
def project_settings(request, project_id):
    """View for project settings page"""
    project = get_object_or_404(Project, pk=project_id)

    # Get all available timezones, excluding deprecated Kiev (use Kyiv instead)
    all_timezones = sorted([tz for tz in available_timezones() if tz != 'Europe/Kiev'])

    # Get project members and invitations
    memberships = ProjectMembership.objects.filter(project=project).select_related('user')
    invitations = Invitation.objects.filter(project=project)

    # Create invitation handler for status checking
    handler = InvitationHandler(project, request.user)

    # Prepare team data for the template
    team_members = []
    for membership in memberships:
        if membership.user == project.owner:
            role = 'owner'
            status = 'active'
        else:
            role = 'member'
            status = 'active'

        team_members.append({
            'name': membership.user.get_full_name() or membership.user.username,
            'email': membership.user.email,
            'role': role,
            'status': status,
            'membership_id': membership.id,
            'is_owner': membership.is_owner,
            'can_remove': membership.user != project.owner,  # Can't remove owner
        })

    # Add pending invitations
    for invitation in invitations.filter(active=False):
        status = handler.get_invitation_status(invitation)

        team_members.append({
            'name': '',
            'email': invitation.email,
            'role': 'member',
            'status': status,
            'invitation_token': invitation.token,
            'is_owner': False,
            'can_remove': True,
            'can_resend': handler.can_resend_invitation(invitation),
            'can_cancel': handler.can_cancel_invitation(invitation),
        })

    # Generate tracking script if project has API key
    tracking_script = None
    if project.api_key:
        tracking_script = generate_tracking_script(project.api_key, {})

    # Check if there is any event data related to this project within the latest 72 hours
    seventy_two_hours_ago = timezone.now() - timezone.timedelta(hours=72)
    has_fresh_data = Event.objects.filter(
        session__visitor__project=project,
        timestamp__gte=seventy_two_hours_ago
    ).exists()
    user_memberships = ProjectMembership.objects.filter(user=request.user).select_related('project')
    context = {
        'project': project,
        'team_members': team_members,
        'tracking_script': tracking_script,
        'is_owner': project.owner == request.user,
        'has_fresh_data': has_fresh_data,
        'memberships': user_memberships,
        'all_timezones': all_timezones
    }

    return render(request, 'projects/settings.html', context)


@login_required
@require_project_owner
def invite_multiple_users(request, project_id):
    """Handle bulk invitation of team members from settings page"""
    project = get_object_or_404(Project, pk=project_id)

    if request.method == 'POST':
        emails_text = request.POST.get('emails', '').strip()

        if not emails_text:
            return redirect('projects:project_settings', project_id=project_id)

        # Use InvitationHandler to process invitations
        handler = InvitationHandler(project, request.user)
        result = handler.send_invitations(emails_text, request)

        # Check for Celery error first
        if result.get('celery_error'):
            return redirect('projects:project_settings', project_id=project_id)

        # Check for validation error
        if result.get('validation_error'):
            return redirect('projects:project_settings', project_id=project_id)

        return redirect('projects:project_settings', project_id=project_id)

    return redirect('projects:project_settings', project_id=project_id)


@login_required
@require_project_owner
def validate_emails(request, project_id):
    """AJAX endpoint to validate email addresses before sending invitations"""
    project = get_object_or_404(Project, pk=project_id)
    if request.method == 'POST':
        try:
            import json
            data = json.loads(request.body)
            emails_text = data.get('emails', '').strip()
            handler = InvitationHandler(project, request.user)
            result = handler.validate_emails(emails_text)

            # Only check Celery if emails are valid
            if result['valid']:
                from .invitation_handler import is_celery_available
                if not is_celery_available():
                    result['celery_error'] = 'Email service is temporarily unavailable. Please try again later.'
                    result['valid'] = False
                    result['error'] = result['celery_error']  # Also set error for backward compatibility

            return JsonResponse(result)

        except json.JSONDecodeError:
            return JsonResponse({
                'valid': False,
                'error': 'Invalid request data.'
            })

    return JsonResponse({
        'valid': False,
        'error': 'Invalid request method.'
    })


def invitation_create_account(request, token):
    """Handle account creation from invitation"""
    invitation = get_object_or_404(Invitation, token=token)

    # If invitation is already accepted, redirect to project settings
    if invitation.active:
        return redirect('projects:project_intro', project_id=invitation.project.pk)

    if invitation.is_expired():
        return redirect('projects:project_list')

    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        terms = request.POST.get('terms')

        # Validate form data
        form_errors = {}
        if not password or len(password) < 8:
            form_errors['password'] = 'Password must be at least 8 characters long.'
        if not terms:
            form_errors['terms'] = 'You must agree to the Terms and Conditions.'

        # Additional password validation using Django's password validators
        if password and len(password) >= 8:
            from django.contrib.auth.password_validation import validate_password
            try:
                validate_password(password)
            except Exception as e:
                form_errors['password'] = str(e)

        if form_errors:
            context = {
                'invitation': invitation,
                'project': invitation.project,
                'inviter_name': invitation.invited_by.get_full_name() or invitation.invited_by.username,
                'form_errors': form_errors,
            }
            return render(request, 'projects/invitation_create_account.html', context)

        # Create user
        from django.contrib.auth import get_user_model
        User = get_user_model()

        try:
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password
            )

            # Auto-login the user
            from django.contrib.auth import login
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')

            # Auto-verify the email address since they confirmed the invitation
            from allauth.account.models import EmailAddress
            email_address, created = EmailAddress.objects.get_or_create(
                user=user,
                email=email,
                defaults={'verified': True, 'primary': True}
            )
            if not created:
                # If email address already exists, mark it as verified
                email_address.verified = True
                email_address.primary = True
                email_address.save()

            # Auto-accept the invitation
            ProjectMembership.objects.get_or_create(
                user=user, project=invitation.project, defaults={'is_owner': False}
            )

            # Mark this invitation as accepted and clean up other pending invitations
            invitation.active = True
            invitation.save()

            # Clean up other pending invitations for the same email
            Invitation.objects.filter(
                project=invitation.project,
                email=invitation.email,
                active=False
            ).exclude(id=invitation.id).delete()

            return redirect('projects:project_intro', project_id=invitation.project.pk)

        except Exception as e:
            form_errors['general'] = 'An error occurred while creating your account. Please try again.'
            context = {
                'invitation': invitation,
                'project': invitation.project,
                'inviter_name': invitation.invited_by.get_full_name() or invitation.invited_by.username,
                'form_errors': form_errors,
            }
            return render(request, 'projects/invitation_create_account.html', context)

    # GET request - show the form
    context = {
        'invitation': invitation,
        'project': invitation.project,
        'inviter_name': invitation.invited_by.get_full_name() or invitation.invited_by.username,
    }
    return render(request, 'projects/invitation_create_account.html', context)


def accept_invitation_action(request, token):
    """Handle the accept button click to join the project"""
    invitation = get_object_or_404(Invitation, token=token, active=False)

    if invitation.is_expired():
        return redirect('projects:project_list')

    # Check if user is authenticated and email matches
    if not request.user.is_authenticated:
        return redirect('account_login')

    if request.user.email.lower() != invitation.email.lower():
        return redirect('projects:project_list')

    # Auto-verify the email address since they confirmed the invitation
    from allauth.account.models import EmailAddress
    email_address, created = EmailAddress.objects.get_or_create(
        user=request.user,
        email=request.user.email,
        defaults={'verified': True, 'primary': True}
    )
    if not created:
        # If email address already exists, mark it as verified
        email_address.verified = True
        email_address.primary = True
        email_address.save()

    # Accept the invitation
    already_member = ProjectMembership.objects.filter(user=request.user, project=invitation.project).exists()

    if not already_member:
        ProjectMembership.objects.get_or_create(
            user=request.user, project=invitation.project, defaults={'is_owner': False}
        )

    # Mark this invitation as accepted and clean up other pending invitations
    invitation.active = True
    invitation.save()

    # Clean up other pending invitations for the same email
    Invitation.objects.filter(
        project=invitation.project,
        email=invitation.email,
        active=False
    ).exclude(id=invitation.id).delete()

    return redirect('projects:project_intro', project_id=invitation.project.pk)


@login_required
@require_project_member
def project_intro(request, project_id):
    """View for project intro page after joining"""
    project = get_object_or_404(Project, pk=project_id)

    context = {
        'project': project,
    }
    return render(request, 'projects/project_intro.html', context)
