from __future__ import annotations

import re
import uuid
from pathlib import Path

from django.utils.timezone import now


UPLOADS_DIR = "uploads"


def normalize_filename(filename: str) -> str:
    name = Path(filename).name
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return safe or f"file_{uuid.uuid4().hex}"


def uploaded_file_path(instance, filename: str) -> str:
    """Return storage path for uploaded files grouped by chat id."""
    timestamp = now().strftime("%Y%m%d")
    safe_name = normalize_filename(filename)
    return f"{UPLOADS_DIR}/{instance.chat_id}/{timestamp}_{uuid.uuid4().hex}_{safe_name}"
