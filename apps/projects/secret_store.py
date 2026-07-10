import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _configured_key_materials():
    configured = str(getattr(settings, 'OPENAI_KEY_ENCRYPTION_KEYS', '') or '')
    materials = [value.strip() for value in configured.split(',') if value.strip()]
    if materials:
        return materials

    secret_key = str(getattr(settings, 'SECRET_KEY', '') or '')
    if not secret_key:
        raise ImproperlyConfigured('SECRET_KEY or OPENAI_KEY_ENCRYPTION_KEYS is required')
    return [f'hymetry-openai:{secret_key}']


def _fernet(material):
    digest = hashlib.sha256(material.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value):
    raw_value = str(value or '').strip()
    if not raw_value:
        raise ValueError('A non-empty secret is required')
    return _fernet(_configured_key_materials()[0]).encrypt(raw_value.encode('utf-8')).decode('ascii')


def decrypt_secret(value):
    encrypted_value = str(value or '').encode('ascii')
    for material in _configured_key_materials():
        try:
            return _fernet(material).decrypt(encrypted_value).decode('utf-8')
        except InvalidToken:
            continue
    raise InvalidToken('The workspace credential cannot be decrypted with the configured keys')
