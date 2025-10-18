from __future__ import annotations

from pathlib import Path

import pytest

from ingestion.constants import UploadStatus
from ingestion.db import get_vector_db_alias
from ingestion.models import N8NEmbed
from ingestion.services import apply_embeddings, create_segments, store_uploaded_file


class DummyAgent:
    text = (
        "Первое тестовое предложение содержит несколько слов. "
        "Второе тестовое предложение содержит несколько слов."
    )
@pytest.mark.django_db(databases="__all__")
def test_segment_embedding_lifecycle(tmp_path):
    text = (
        "Первое тестовое предложение содержит несколько слов. "
        "Второе тестовое предложение содержит несколько слов."
    )
    source = tmp_path / "doc.txt"
    source.write_text(text, encoding="utf-8")

    uploaded = store_uploaded_file(
        chat_id=555,
        file_path=source,
        file_name="doc.txt",
        mime_type="text/plain",
    )
    uploaded.refresh_from_db()
    assert uploaded.status == UploadStatus.PENDING.value

    segments = create_segments(uploaded, text)
    assert segments

    apply_embeddings(uploaded, segments, agent=DummyAgent())

    alias = get_vector_db_alias()
    prefix = f"{uploaded.file_name}|{uploaded.id}|"
    entries = list(
        N8NEmbed.objects.using(alias)
        .filter(tittle__startswith=prefix)
        .order_by("id")
    )
    assert len(entries) == len(segments)
    assert all(len(entry.embeding) == 1536 for entry in entries)

    first_tittle = entries[0].tittle
    N8NEmbed.objects.using(alias).filter(tittle=first_tittle).delete()
    assert (
        N8NEmbed.objects.using(alias)
        .filter(tittle=first_tittle)
        .count()
        == 0
    )
