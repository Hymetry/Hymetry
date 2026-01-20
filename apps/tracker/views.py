import re
import requests

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse, Http404, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.projects.models import ProjectMembership
from apps.tracker.all_sessions_bubbles_view import AllSessionsBubblesView
from apps.tracker.models import Session
from apps.tracker.recording_mixins import RecordingViewMixin
from apps.tracker.session_tracker import SessionTracker


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def record_event(request):
    """Record a single event or batch of events."""
    # Handle preflight request
    if request.method == "OPTIONS":
        response = JsonResponse({})
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    tracker = SessionTracker(request)

    # Parse request data
    if not tracker.parse_request():
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    try:
        # Find or create session
        tracker.find_session()

        # Get or create page
        tracker.get_or_create_page()

        # Process events
        tracker.process_events()

        # Update session activity after events are persisted
        tracker.update_session_activity()

        # Get response
        response = tracker.get_response()
        response["Access-Control-Allow-Origin"] = "*"
        return response

    except Exception as e:
        print(f"Error processing request: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def recordings(request, project_id):
    """Cache-based version using BubbleCacheManager for optimized performance."""
    # Check if user has access to this project
    is_member = ProjectMembership.objects.filter(project_id=project_id, user=request.user).exists()
    if not is_member:
        raise PermissionDenied('You do not have access to this project.')

    view = AllSessionsBubblesView(request, project_id)
    r = view.render()
    return r


@login_required
@require_http_methods(["GET"])
def recording(request, project_id, session_id):
    """Display single rrweb player for a specific session with consolidated timeline."""
    try:
        # Check if user has access to this project
        is_member = ProjectMembership.objects.filter(project_id=project_id, user=request.user).exists()
        if not is_member:
            raise PermissionDenied('You do not have access to this project.')

        # Get session and verify it belongs to the specified project
        session = Session.objects.select_related('visitor__project').get(session_id=session_id)
        if session.visitor.project.id != int(project_id):
            raise Http404('Session not found in this project.')

        mixin = RecordingViewMixin(request, project_id, session_id)
        session_bubbles_data = mixin.get_bubble_data(session)

        return render(request, 'tracker/recording.html', {
            'session': session,
            'session_bubbles_data': session_bubbles_data,  # Pass session bubbles as Python list
            'project_id': project_id,
            'session_id': session_id
        })
    except Session.DoesNotExist:
        raise Http404('Session not found.')


@login_required
@require_http_methods(["GET"])
def get_consolidated_data(request, project_id, session_id):
    """Ajax endpoint to get consolidated timeline data for a specific session."""
    try:
        # Check if user has access to this project
        is_member = ProjectMembership.objects.filter(project_id=project_id, user=request.user).exists()
        if not is_member:
            raise PermissionDenied('You do not have access to this project.')

        # Verify session belongs to the specified project
        session = Session.objects.select_related('visitor__project').get(session_id=session_id)
        if session.visitor.project.id != int(project_id):
            return JsonResponse({'error': 'Session not found in this project.'}, status=404)

        # Get consolidated timeline data
        from apps.tracker.tools import get_consolidated_timeline_data
        consolidated_data = get_consolidated_timeline_data(request, session_id)

        return JsonResponse({
            'success': True,
            'data': consolidated_data
        })
    except Session.DoesNotExist:
        return JsonResponse({'error': 'Session not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET", "HEAD", "OPTIONS"])
def asset_proxy(request):
    """
    Proxy external assets to solve CORS issues.
    Replaces the Cloudflare worker for self-hosted deployments.
    """
    # Handle CORS preflight
    if request.method == "OPTIONS":
        response = HttpResponse()
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type"
        response["Access-Control-Max-Age"] = "86400"
        return response

    target_url = request.GET.get('url')
    if not target_url:
        return HttpResponse("missing ?url=", status=400)

    # Validate URL format
    if not re.match(r'^https?://', target_url, re.IGNORECASE):
        return HttpResponse("bad url", status=400)

    try:
        # Fetch the upstream resource
        upstream_response = requests.get(
            target_url,
            headers={'Origin': request.build_absolute_uri('/')},
            timeout=30,
            stream=True
        )

        # Create response with the upstream content
        response = HttpResponse(
            upstream_response.content,
            status=upstream_response.status_code,
            content_type=upstream_response.headers.get('Content-Type', 'application/octet-stream')
        )

        # Add CORS headers
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
        response["Vary"] = "Origin"

        # Set cache headers if not present
        if 'Cache-Control' not in upstream_response.headers:
            response["Cache-Control"] = "public, max-age=2592000"
        else:
            response["Cache-Control"] = upstream_response.headers['Cache-Control']

        return response

    except requests.Timeout:
        return HttpResponse("upstream timeout", status=504)
    except requests.RequestException as e:
        return HttpResponse(f"upstream error: {str(e)}", status=502)
