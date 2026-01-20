import hashlib
import hmac
import logging
import os
import subprocess

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt


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


logger = logging.getLogger(__name__)

@csrf_exempt
def github_push_event_handler(request):
    logger.info(f"Webhook called: method={request.method}, headers={dict(request.headers)}")

    if request.method != "POST":
        logger.warning("Invalid method")
        return HttpResponse("Method not allowed", status=405)

    # Перевірка GitHub signature
    signature = request.headers.get("X-Hub-Signature-256")
    if signature is None:
        logger.warning("Missing signature")
        return HttpResponseForbidden("Missing signature")

    secret = settings.GITHUB_SECRET.encode()
    payload = request.body
    mac = hmac.new(secret, msg=payload, digestmod=hashlib.sha256)
    expected_signature = "sha256=" + mac.hexdigest()

    if not hmac.compare_digest(signature, expected_signature):
        logger.warning("Invalid signature")
        return HttpResponseForbidden("Invalid signature")

    event = request.headers.get("X-GitHub-Event")
    logger.info(f"GitHub event: {event}")

    if event == "push":
        logger.info("Starting deploy.sh")
        log_file = "/var/log/github_deploy.log"
        try:
            #os.system("/opt/productpathpro/github-deploy.sh")
            os.system("sudo systemctl start deploy.service")
            return HttpResponse("Deploy started", status=200)
        except Exception as e:
            logger.exception(f"Failed to start deploy.sh: {e}")
            return HttpResponse("Deploy failed", status=500)

    logger.info("Event ignored")
    return HttpResponse("Event ignored", status=200)