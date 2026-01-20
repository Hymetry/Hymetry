import json

from allauth.account.views import ConfirmEmailView
from allauth.account.views import LoginView
from allauth.account.views import SignupView as AllauthSignupView
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render, redirect
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

from apps.users.forms import ProfileNameForm, ProfilePasswordForm


# User Authentication Views
def custom_email_verification_sent(request):
    """Custom view to handle email verification sent page"""
    # Get the email from the session or request
    email = request.session.get('signup_email', '')

    # If no email in session, try to get it from the request
    if not email:
        email = request.GET.get('email', '')

    # Render our custom template
    return render(request, 'users/email_verification_sent.html', {'email': email})


class CustomSignupView(AllauthSignupView):
    """Custom signup view that redirects to our custom email-sent URL"""
    template_name = 'users/sign_up.html'

    def form_valid(self, form):
        """Override form_valid to check email uniqueness and redirect to our custom URL"""
        # Get the email from the form
        email = form.cleaned_data.get('email', '')
        
        # Check if email already exists
        User = get_user_model()
        if User.objects.filter(email__iexact=email).exists():
            # Add error to the form and keep the email in the field
            form.add_error('email', 'A user with this email address already exists.')
            # Make form.data mutable and preserve the email
            if hasattr(form.data, '_mutable'):
                form.data._mutable = True
            form.data['email'] = email
            return self.form_invalid(form)
        
        # Store email in session for the email-sent page
        self.request.session['signup_email'] = email

        # Call parent form_valid to handle the signup
        response = super().form_valid(form)

        # Override the redirect to our custom URL
        return HttpResponseRedirect('/sign-up/email-sent/')


def sign_in(request):
    return LoginView.as_view(template_name='users/sign_in.html')(request)


@login_required
def welcome(request):
    """Welcome page view for newly signed up users."""
    return render(request, 'users/welcome.html')


# Password Reset Views
def password_reset_request(request):
    """Handle password reset request - ask for email"""
    if request.method == 'POST':
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            # Store email in session for the email-sent page
            request.session['reset_email'] = email
            form.save(
                request=request,
                email_template_name='account/email/password_reset_email.html',
                subject_template_name='account/email/password_reset_subject.txt'
            )
            return redirect('password_reset_email_sent')
    else:
        form = PasswordResetForm()

    return render(request, 'users/password_reset_request.html', {'form': form})


def password_reset_email_sent(request):
    """Show email sent confirmation page"""
    email = request.session.get('reset_email', '')
    return render(request, 'users/password_reset_email_sent.html', {'email': email})


def password_reset_set_new(request, uidb64, token):
    """Handle setting new password"""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = get_user_model().objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, get_user_model().DoesNotExist, ValidationError):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        if request.method == 'POST':
            password = request.POST.get('new_password1')
            errors = []

            # Validate password
            if not password:
                errors.append('Password is required.')
            elif len(password) < 8:
                errors.append('Password must be at least 8 characters long.')
            else:
                try:
                    validate_password(password, user)
                except ValidationError as e:
                    errors.extend(e.messages)

            if errors:
                # Return form with errors
                form = SetPasswordForm(user)
                form.errors['new_password1'] = errors
                return render(request, 'users/password_reset_set_new.html', {'form': form})
            else:
                # Set the password and redirect to success
                user.set_password(password)
                user.save()
                return redirect('password_reset_success')
        else:
            form = SetPasswordForm(user)

        return render(request, 'users/password_reset_set_new.html', {'form': form})
    else:
        # Invalid token
        return redirect('password_reset_request')


def password_reset_success(request):
    """Show password reset success page"""
    return render(request, 'users/password_reset_success.html')


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


class AutoLoginConfirmEmailView(ConfirmEmailView):
    def get_redirect_url(self):
        return "/welcome/"

    def get(self, *args, **kwargs):
        # Get the confirmation object
        confirmation = self.get_object()
        
        # Confirm the email
        confirmation.confirm(self.request)

        # Get the user from the email address
        user = confirmation.email_address.user
        
        # Log in the user
        if user:
            from allauth.account.utils import perform_login
            perform_login(self.request, user, email_verification='optional')
        
        # Always redirect to welcome
        return redirect("/welcome/")
