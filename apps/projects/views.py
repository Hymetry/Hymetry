import json
from zoneinfo import ZoneInfo, available_timezones

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render, redirect
from django.utils import timezone

from apps.tracker.models import Event
from apps.users.forms import ProjectForm
from .decorators import require_project_member, require_project_owner
from .models import Project, ProjectMembership, ChatGptKey, UserLeftLastProject
from .utils import generate_tracking_script

User = get_user_model()


def check_if_any_superuser_exists():
    User = get_user_model()
    if User.objects.filter(is_superuser=True).exists():
        print("At least one superuser exists.")
        return True
    else:
        print("No superusers found in the database.")
        return False


def homepage(request):
    if not check_if_any_superuser_exists():
        return render(request, "users/superadmin_password.html")
    return redirect('project_list')


def superadmin_required(view_func):
    decorated_view_func = user_passes_test(
        lambda u: u.is_active and u.is_superuser
    )(view_func)
    return decorated_view_func


@login_required
def project_list(request):
    """View for the modern all projects page"""
    memberships = ProjectMembership.objects.filter(user=request.user).select_related('project')
    return render(request, 'projects/project_list.html', {'memberships': memberships})


@login_required
@superadmin_required
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
                if timezone_value == "Europe/Kiev":
                    timezone_value = "Europe/Kyiv"
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
@superadmin_required
def project_delete(request, pk):
    project = get_object_or_404(Project, pk=pk, owner=request.user)
    if request.method == 'POST':
        project.delete()
    return redirect('projects:project_list')


@login_required
@require_project_member
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
        # User removes themselves - if this is their last project, save to UserLeftLastProject
        user = membership.user
        is_last_project = ProjectMembership.objects.filter(user=user).count() == 1
        membership.delete()
        if is_last_project:
            UserLeftLastProject.objects.update_or_create(user=user, defaults={'project': project})
        return redirect('projects:project_list')
    elif request.user == project.owner:
        # Admin removes user - clear UserLeftLastProject, delete membership, delete user if no other projects
        user_to_remove = membership.user
        UserLeftLastProject.objects.filter(user=user_to_remove).delete()
        membership.delete()
        if not ProjectMembership.objects.filter(user=user_to_remove).exists():
            user_to_remove.delete()
        return redirect('projects:project_settings', project_id=project_id)
    else:
        return redirect('projects:project_settings', project_id=project_id)


@login_required
@require_project_member
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
@require_project_member
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

    tz_map = {
        "Europe/Kiev": "Europe/Kyiv"
    }

    all_timezones = sorted(
        [tz_map.get(tz, tz) for tz in available_timezones()]
    )

    # Get project members and invitations
    memberships = ProjectMembership.objects.filter(project=project).select_related('user')

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
            'can_remove': membership.user != project.owner,
            'user_id': membership.user_id,
        })

    # Add users who left this project by themselves (from UserLeftLastProject)
    for record in UserLeftLastProject.objects.filter(project=project).select_related('user'):
        team_members.append({
            'name': record.user.get_full_name() or record.user.username,
            'email': record.user.email,
            'role': 'member',
            'status': 'left_project',
            'membership_id': None,
            'is_owner': False,
            'can_remove': project.owner == request.user,
            'user_id': record.user_id,
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

    chatgpt_key_value = ''
    chatgpt_key_is_valid = False
    chatgpt_key_needs_check = False
    chatgpt_key = ChatGptKey.objects.filter(project=project).first()
    if chatgpt_key is not None and chatgpt_key.key:
        chatgpt_key_value = chatgpt_key.key
        chatgpt_key_needs_check = not chatgpt_key.is_checked
        chatgpt_key_is_valid = chatgpt_key.check_result if chatgpt_key.is_checked else None

    context = {
        'project': project,
        'team_members': team_members,
        'tracking_script': tracking_script,
        'is_owner': project.owner == request.user,
        'has_fresh_data': has_fresh_data,
        'memberships': user_memberships,
        'all_timezones': all_timezones,
        'chatgpt_key_value': chatgpt_key_value,
        'chatgpt_key_needs_check': chatgpt_key_needs_check,
        'chatgpt_key_is_valid': chatgpt_key_is_valid
    }

    return render(request, 'projects/settings.html', context)


@login_required
@require_project_owner
def delete_left_user(request, project_id, user_id):
    """
    Delete a user account that appears as 'Inactive (left project)'.

    Safety:
    - Only the project owner can do this
    - Only deletes the user if they are in no projects
    """
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    record = UserLeftLastProject.objects.filter(user_id=user_id, project=project).select_related('user').first()
    if not record:
        return redirect('projects:project_settings', project_id=project_id)

    user = record.user
    record.delete()

    if not ProjectMembership.objects.filter(user=user).exists():
        user.delete()

    return redirect('projects:project_settings', project_id=project_id)


@login_required
@require_project_owner
def create_and_add_user_to_project(request, project_id):
    """
    It creates a user and adds him to a project
    """
    if not request.method == 'POST':
        return JsonResponse({'error': 'Only POST method allowed'})

    data = json.loads(request.body)

    email = data.get('email')
    password = data.get('password')

    # Validate form data
    if not email:
        return JsonResponse({'error': 'Email is required'})

    if not password or len(password) < 8:
        return JsonResponse({'error': 'Password must contain at least 8 characters'})

    # Create user
    from django.contrib.auth import get_user_model
    User = get_user_model()

    try:
        user, created = User.objects.get_or_create(
            username=email,
            defaults={'email': email}
        )
        if created:
            user.set_password(password)  # hashes the password before storing
            user.save()

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
            user=user, project_id=project_id, defaults={'is_owner': False}
        )
        # User is back in a project - remove from UserLeftLastProject if present
        UserLeftLastProject.objects.filter(user=user).delete()
        return JsonResponse({'error': ''})
    except Exception as e:
        return JsonResponse({'error': f'Cannot add user to project. The error is {e}'})


@login_required
@require_project_owner
def save_chatgpt_key(request, project_id):
    """Add or update ChatGPT API key for the project (Ajax). Only the project owner can do this."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'})

    project = get_object_or_404(Project, pk=project_id)

    # Accept JSON or form-encoded body
    if request.content_type and 'application/json' in request.content_type:
        try:
            data = json.loads(request.body)
            key = (data.get('key') or '').strip()
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON.'})
    else:
        key = (request.POST.get('key') or '').strip()

    if not key:
        return JsonResponse({'success': False, 'error': 'API key is required.'})

    chatgpt_key, created = ChatGptKey.objects.get_or_create(project=project, defaults={'key': key})
    if not created:
        chatgpt_key.key = key
    chatgpt_key.is_checked = False
    chatgpt_key.check_result = None
    chatgpt_key.save()

    return JsonResponse({'success': True})


@login_required
@require_project_member
def check_chatgpt_key(request, project_id):
    """Check if the project's ChatGPT API key is valid (Ajax). Saves result to DB so all users see it."""
    if request.method != 'GET':
        return JsonResponse({'valid': False, 'error': 'Invalid request method.'})

    project = get_object_or_404(Project, pk=project_id)
    chatgpt_key = ChatGptKey.objects.filter(project=project).first()
    if not chatgpt_key or not chatgpt_key.key:
        return JsonResponse({'valid': False})

    try:
        valid = chatgpt_key.key_is_valid()
        chatgpt_key.is_checked = True
        chatgpt_key.check_result = valid
        chatgpt_key.save(update_fields=['is_checked', 'check_result'])
        return JsonResponse({'valid': valid})
    except Exception:
        chatgpt_key.is_checked = True
        chatgpt_key.check_result = False
        chatgpt_key.save(update_fields=['is_checked', 'check_result'])
        return JsonResponse({'valid': False})


@login_required
@require_project_owner
def remove_chatgpt_key(request, project_id):
    """Remove the project's ChatGPT API key (Ajax). Only the project owner can do this."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'})

    project = get_object_or_404(Project, pk=project_id)
    ChatGptKey.objects.filter(project=project).delete()
    return JsonResponse({'success': True})
