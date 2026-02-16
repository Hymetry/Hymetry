from django.contrib.auth import get_user_model
from django.shortcuts import render, redirect


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
