from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


def _get_fernet() -> Fernet:
    key = getattr(settings, "FERNET_SECRET", None)
    if not key:
        raise ImproperlyConfigured("FERNET_SECRET is not configured.")
    if isinstance(key, str):
        key_bytes = key.encode("utf-8")
    else:
        key_bytes = key
    return Fernet(key_bytes)


def _encrypt(value: str) -> str:
    fernet = _get_fernet()
    token = fernet.encrypt(value.encode("utf-8"))
    return token.decode("utf-8")


def _decrypt(value: str) -> str:
    if value in (None, ""):
        return value
    fernet = _get_fernet()
    try:
        decrypted = fernet.decrypt(value.encode("utf-8"))
    except (InvalidToken, ValueError):
        return value
    return decrypted.decode("utf-8")


class _EncryptedFieldMixin:
    description = "Field that transparently encrypts values at rest using Fernet symmetric encryption."

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, ""):
            return value
        if not isinstance(value, str):
            value = str(value)
        return _encrypt(value)

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return value
        if not isinstance(value, str):
            return value
        return _decrypt(value)

    def to_python(self, value):
        if value in (None, ""):
            return value
        if isinstance(value, str):
            return _decrypt(value)
        return super().to_python(value)


class EncryptedTextField(_EncryptedFieldMixin, models.TextField):
    pass


class EncryptedCharField(_EncryptedFieldMixin, models.CharField):
    pass
