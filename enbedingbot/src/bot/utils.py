from __future__ import annotations

from typing import Iterable, List

from django.utils import timezone

from ingestion.constants import UploadStatus
from ingestion.models import UploadedFile

STATUS_LABELS = {
    UploadStatus.PENDING.value: "Pending",
    UploadStatus.PROCESSING.value: "Processing",
    UploadStatus.READY.value: "Ready",
    UploadStatus.FAILED.value: "Failed",
}


def human_status(uploaded: UploadedFile) -> str:
    return STATUS_LABELS.get(uploaded.status, uploaded.status)


def format_history(files: Iterable[UploadedFile]) -> str:
    rows: List[str] = []
    for item in files:
        timestamp = timezone.localtime(item.uploaded_at).strftime("%d.%m %H:%M")
        status = human_status(item)
        rows.append(f"{timestamp} - {item.file_name} ({status})")
    return "\n".join(rows) if rows else "No files yet."
