from __future__ import annotations

import hashlib

from django.db import models
from django.utils import timezone

from bot.fields import EncryptedTextField


class UserProfile(models.Model):
    telegram_chat_id = models.BigIntegerField(unique=True, db_index=True)
    telegram_username = models.CharField(max_length=255, blank=True)
    phone_number_e164 = models.CharField(max_length=32, blank=True)
    display_name = models.CharField(max_length=255, blank=True)
    onboarding_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        username = self.telegram_username or "anonymous"
        return f"{username} ({self.telegram_chat_id})"


class UserCredential(models.Model):
    profile = models.OneToOneField(
        UserProfile,
        on_delete=models.CASCADE,
        related_name="credential",
    )
    supabase_project_id = models.CharField(max_length=150)
    vector_db_host = models.CharField(max_length=255)
    vector_db_port = models.PositiveIntegerField(default=5432)
    vector_db_name = models.CharField(max_length=128)
    vector_db_user = models.CharField(max_length=128)
    vector_db_password = EncryptedTextField()
    supabase_rest_url = models.URLField(blank=True)
    supabase_service_role = EncryptedTextField(blank=True)
    openai_api_key = EncryptedTextField()
    vector_schema_name = models.CharField(max_length=128)
    openai_key_fingerprint = models.CharField(max_length=64, blank=True)
    last_validated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["supabase_project_id", "vector_schema_name"],
                name="unique_project_schema",
            )
        ]

    def __str__(self) -> str:
        return f"Credentials for {self.profile_id}"

    def mark_validated(self) -> None:
        self.last_validated_at = timezone.now()
        self.save(update_fields=["last_validated_at"])

    def update_openai_fingerprint(self, api_key: str) -> None:
        fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        if self.openai_key_fingerprint != fingerprint:
            self.openai_key_fingerprint = fingerprint
            self.save(update_fields=["openai_key_fingerprint"])


class UserValidationEvent(models.Model):
    profile = models.ForeignKey(
        UserProfile,
        related_name="validation_events",
        on_delete=models.CASCADE,
    )
    success = models.BooleanField(default=False)
    context = models.CharField(max_length=64)
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        status = "ok" if self.success else "fail"
        return f"{self.profile_id}:{status}"
