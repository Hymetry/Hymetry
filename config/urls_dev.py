from django.urls import path, include
from django.http import HttpResponse
import os
from django.conf import settings

def serve_main_js(request):
    """Serve main.js file for development"""
    js_path = os.path.join(settings.BASE_DIR, 'static', 'js', 'main.js')
    try:
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return HttpResponse(content, content_type='application/javascript')
    except FileNotFoundError:
        return HttpResponse('// main.js not found', content_type='application/javascript')

def serve_test_page(request):
    """Serve playground index.html for development"""
    html_path = os.path.join(settings.BASE_DIR, 'playground', 'public', 'index.html')
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return HttpResponse(content, content_type='text/html')
    except FileNotFoundError:
        return HttpResponse('<h1>Test page not found</h1><p>playground/public/index.html does not exist</p>', content_type='text/html')

def serve_about_page(request):
    """Serve playground index.html for development"""
    html_path = os.path.join(settings.BASE_DIR, 'playground', 'public', 'about.html')
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return HttpResponse(content, content_type='text/html')
    except FileNotFoundError:
        return HttpResponse('<h1>Test page not found</h1><p>playground/public/about.html does not exist</p>', content_type='text/html')

def serve_lib_min_js(request):
    """Serve tracker lib.min.js file for development"""
    js_path = os.path.join(settings.BASE_DIR, 'static', 'js', 'tracker', 'lib.min.js')
    try:
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return HttpResponse(content, content_type='application/javascript')
    except FileNotFoundError:
        return HttpResponse('// lib.min.js not found', content_type='application/javascript')

# Include the main URL patterns
from config.urls import urlpatterns as main_urlpatterns

# Development-specific URL patterns
dev_urlpatterns = [
    path('main.js', serve_main_js, name='main_js_dev'),
    path('test/', serve_test_page, name='test_page_dev'),
    path('about/', serve_about_page, name='about_page_dev'),
    path('lib.min.js', serve_lib_min_js, name='lib_min_js_dev'),
]

# Combine main URLs with development URLs
urlpatterns = dev_urlpatterns + main_urlpatterns 