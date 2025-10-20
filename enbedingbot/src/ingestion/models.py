from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import models
from pgvector.django import VectorField

from ingestion.constants import UploadStatus
from ingestion.storage import uploaded_file_path
from ingestion.vector_store import VectorStoreService

if TYPE_CHECKING:  # pragma: no cover
    from bot.models import UserCredential


class UploadedFile(models.Model):
    profile = models.ForeignKey(
        "bot.UserProfile",
        null=True,
        blank=True,
        related_name="uploads",
        on_delete=models.CASCADE,
    )
    chat_id = models.BigIntegerField(db_index=True)
    file_name = models.CharField(max_length=255)
    original_file = models.FileField(upload_to=uploaded_file_path)
    file_size = models.BigIntegerField()
    mime_type = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=32,
        choices=[(status.value, status.value) for status in UploadStatus],
        default=UploadStatus.PENDING.value,
    )
    error_message = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-uploaded_at",)

    def __str__(self) -> str:
        return f"{self.file_name} ({self.chat_id})"

    def _title_prefix(self) -> str:
        return f"{self.file_name}|{self.id}|"

    def segments_count(self) -> int:
        credential = getattr(self.profile, "credential", None)
        if not credential:
            return 0
        store = VectorStoreService(credential)
        return store.count_segments(self._title_prefix())

    def fetch_segments(self):
        credential = getattr(self.profile, "credential", None)
        if not credential:
            return []
        store = VectorStoreService(credential)
        return store.fetch_segments(self._title_prefix())


class N8NEmbed(models.Model):
    tittle = models.CharField(max_length=255)
    body = models.TextField()
    embeding = VectorField(dimensions=1536)

    class Meta:
        db_table = 'n8n-embed'
        ordering = ('id',)

    def __str__(self) -> str:
        return self.tittle
