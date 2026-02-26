import json

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth import login
from apps.projects.views import check_if_any_superuser_exists
from apps.users.forms import ProfileNameForm, ProfilePasswordForm
from django.contrib import messages


def create_admin_account(request):
    if request.method != 'POST':
        messages.error(request, 'Invalid request method')
        return redirect('index')

    email = request.POST.get('email')
    password = request.POST.get('password')

    if not (email and len(password) > 7):
        messages.error(request, 'Email and Password (min length is 8) fields are required')
        return redirect('index')

    if check_if_any_superuser_exists():
        messages.error(request, 'Superuser exists')
        return redirect('index')

    # Create user
    User = get_user_model()

    try:
        user = User.objects.create_superuser(
            username=email,
            email=email,
            password=password
        )
        # Autologin the user
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        return redirect('project_list')
    except Exception as e:
        messages.error(request, e)
        print(f"Error creating admin account: {e}")
        return redirect('index')


@login_required
def user_profile(request):
    """View for user profile page with form handling"""
    context = {'user': request.user}

    # Handle name change form
    if request.method == 'POST' and 'change_name' in request.POST:
        name_form = ProfileNameForm(request.POST, user=request.user)
        if name_form.is_valid():
            name_form.save()
            return redirect('users:user_profile')
        else:
            # Don't redirect, just render the page with errors
            context['name_form'] = name_form
            context['show_name_modal'] = True
            # Initialize password form for the template
            context['password_form'] = ProfilePasswordForm(request.user)
            return render(request, 'users/profile.html', context)
    else:
        context['name_form'] = ProfileNameForm(user=request.user)

    # Handle password change form
    if request.method == 'POST' and 'change_password' in request.POST:
        password_form = ProfilePasswordForm(request.user, request.POST)
        if password_form.is_valid():
            # Update the password without logging out the user
            user = password_form.save()
            # Update the session to keep the user logged in
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, user)
            return redirect('users:user_profile')
        else:
            # Don't redirect, just render the page with errors
            context['password_form'] = password_form
            context['show_password_modal'] = True
            # Initialize name form for the template
            context['name_form'] = ProfileNameForm(user=request.user)
            return render(request, 'users/profile.html', context)
    else:
        context['password_form'] = ProfilePasswordForm(request.user)

    return render(request, 'users/profile.html', context)


@login_required
def validate_old_password(request):
    """AJAX endpoint to validate old password"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            old_password = data.get('old_password', '')

            # Check if the old password is correct
            if request.user.check_password(old_password):
                return JsonResponse({'valid': True})
            else:
                return JsonResponse({'valid': False, 'error': 'Your old password was entered incorrectly'})
        except json.JSONDecodeError:
            return JsonResponse({'valid': False, 'error': 'Invalid request data'})

    return JsonResponse({'valid': False, 'error': 'Invalid request method'})
