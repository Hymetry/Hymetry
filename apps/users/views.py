import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.views import LoginView

from apps.users.forms import EmailAuthenticationForm, ProfileNameForm, ProfilePasswordForm
from apps.users.services import (
    InitialAdminAlreadyConfigured,
    create_initial_admin,
    initial_admin_is_required,
)
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_http_methods


class InitialSetupAwareLoginView(LoginView):
    template_name = 'users/sign_in.html'
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        if initial_admin_is_required():
            return redirect('users:initial_admin_setup')
        return super().dispatch(request, *args, **kwargs)


@require_http_methods(['GET', 'POST'])
def initial_admin_setup(request):
    if not initial_admin_is_required():
        return redirect('project_list' if request.user.is_authenticated else 'sign_in')

    context = {
        'submitted_email': '',
        'terms_checked': False,
        'form_errors': [],
    }
    if request.method == 'POST':
        email = str(request.POST.get('email', '') or '')
        password = str(request.POST.get('password', '') or '')
        password_confirm = str(request.POST.get('password_confirm', '') or '')
        terms_checked = request.POST.get('terms') == 'on'
        form_errors = []

        if not terms_checked:
            form_errors.append('Accept the license terms to continue.')
        if password != password_confirm:
            form_errors.append('The passwords do not match.')

        if not form_errors:
            try:
                user = create_initial_admin(email=email, password=password)
            except InitialAdminAlreadyConfigured:
                return redirect('sign_in')
            except ValidationError as exc:
                form_errors.extend(exc.messages)
            else:
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                return redirect('projects:project_list')

        context.update({
            'submitted_email': email,
            'terms_checked': terms_checked,
            'form_errors': form_errors,
        })

    return render(request, 'users/superadmin_password.html', context)


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
