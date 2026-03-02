"""
Config utilities for loading values from .env (same pattern as config.settings.base).
"""
import os

from dotenv import load_dotenv

# Load environment variables from .env file (same as base.py)
load_dotenv()


def get_django_settings_module() -> str:
    """
    Get Django settings module from .env.
    Falls back to config.settings.prod if DJANGO_SETTINGS_MODULE is not set.
    """
    return os.getenv('DJANGO_SETTINGS_MODULE', 'config.settings.prod')
