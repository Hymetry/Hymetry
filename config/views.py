from django.shortcuts import render


def permission_denied(request, exception=None):
    """
    Custom 403 handler that provides better error messages.
    """
    context = {
        'exception': str(exception) if exception else None,
    }
    return render(request, '403.html', context, status=403)


def page_not_found(request, exception=None):
    """
    Custom 404 handler.
    """
    return render(request, '404.html', {}, status=404)


def server_error(request):
    """
    Custom 500 handler.
    """
    return render(request, '500.html', {}, status=500)
