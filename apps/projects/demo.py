from django.http import Http404


DEMO_PROJECT_DISPLAY_NAME = 'Hosted demo'


def get_demo_project():
    raise Http404('The OSS edition does not contain a local demo project.')


def is_demo_project(project):
    return False


def ensure_project_writable(project):
    return project
