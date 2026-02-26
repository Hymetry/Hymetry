from django import forms
from django.contrib.auth.forms import PasswordChangeForm

from apps.projects.models import Project


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['name']


class ProfileNameForm(forms.Form):
    first_name = forms.CharField(
        max_length=30,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'shadow-sm appearance-none border rounded w-full py-3 px-3 text-gray-700 leading-tight focus:ring-2 focus:ring-blue-500 focus:outline-none focus:border-blue-500',
            'placeholder': 'Enter your first name'
        })
    )
    last_name = forms.CharField(
        max_length=30,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'shadow-sm appearance-none border rounded w-full py-3 px-3 text-gray-700 leading-tight focus:ring-2 focus:ring-blue-500 focus:outline-none focus:border-blue-500',
            'placeholder': 'Enter your last name'
        })
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.user:
            self.fields['first_name'].initial = self.user.first_name
            self.fields['last_name'].initial = self.user.last_name

    def save(self):
        if self.user:
            self.user.first_name = self.cleaned_data['first_name']
            self.user.last_name = self.cleaned_data['last_name']
            self.user.save()
        return self.user


class ProfilePasswordForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Remove the new_password2 field (confirmation)
        if 'new_password2' in self.fields:
            del self.fields['new_password2']
        # Update widget classes for better styling
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': 'shadow-sm appearance-none border rounded w-full py-3 px-3 text-gray-700 leading-tight focus:ring-2 focus:ring-blue-500 focus:outline-none focus:border-blue-500'
            })


from django import forms
from django.contrib.auth import password_validation


class SinglePasswordResetForm(forms.Form):
    password = forms.CharField(
        label="New password",
        widget=forms.PasswordInput,
        strip=False,
        help_text=password_validation.password_validators_help_text_html(),
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        kwargs.pop('temp_key', None)  # discard unused keys passed by the view
        kwargs.pop('uid', None)
        kwargs.pop('key', None)
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data.get('password')
        password_validation.validate_password(password, self.user)
        return password

    def save(self):
        password = self.cleaned_data["password"]
        self.user.set_password(password)
        self.user.save()
        return self.user
