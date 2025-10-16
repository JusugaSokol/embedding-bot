from __future__ import annotations

from enum import Enum


class UploadStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


SUPPORTED_EXTENSIONS = {".docx", ".csv", ".txt", ".md"}
MAX_FILE_SIZE_MB = 15
