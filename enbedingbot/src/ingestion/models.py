from __future__ import annotations

from django.db import models
from pgvector.django import VectorField

from ingestion.constants import UploadStatus
from ingestion.db import get_vector_db_alias
from ingestion.storage import uploaded_file_path


class UploadedFile(models.Model):
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

    def segments_queryset(self):
        alias = get_vector_db_alias()
        prefix = self._title_prefix()
        return (
            N8NEmbed.objects.using(alias)
            .filter(tittle__startswith=prefix)
            .order_by("id")
        )

    def segments_count(self) -> int:
        return self.segments_queryset().count()


class N8NEmbed(models.Model):
    tittle = models.CharField(max_length=255)
    body = models.TextField()
    embeding = VectorField(dimensions=1536)

    class Meta:
        db_table = 'n8n-embed'
        ordering = ('id',)

    def __str__(self) -> str:
        return self.tittle
