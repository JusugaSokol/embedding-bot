from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from ingestion.constants import UploadStatus
from ingestion.db import get_vector_db_alias
from ingestion.models import N8NEmbed
from ingestion.services import (
    EmptyFileError,
    UnsupportedFormatError,
    build_export_archive,
    process_uploaded_file,
    store_uploaded_file,
    validate_extension,
)

    text = (
        "Первое тестовое предложение содержит несколько слов и формирует сегмент. "
        "Второе тестовое предложение содержит несколько слов и формирует сегмент. "
        "Третье тестовое предложение содержит несколько слов и формирует сегмент. "
        "Четвёртое тестовое предложение содержит несколько слов и формирует сегмент."

@pytest.mark.django_db(databases="__all__")
def test_process_uploaded_file_creates_segments_and_embeddings(tmp_path):
    text = (
        "Первое тестовое предложение содержит несколько слов и формирует сегмент. "
        "Второе тестовое предложение содержит несколько слов и формирует сегмент. "
        "Третье тестовое предложение содержит несколько слов и формирует сегмент. "
        "Четвёртое тестовое предложение содержит несколько слов и формирует сегмент."
    )
    sample_path = tmp_path / "sample.txt"
    sample_path.write_text(text, encoding="utf-8")

    uploaded = store_uploaded_file(
        chat_id=111,
        file_path=sample_path,
        file_name="sample.txt",
        mime_type="text/plain",
    )

    process_uploaded_file(uploaded, agent=DummyAgent())
    uploaded.refresh_from_db()

    text = (
        "Первая длинная строка содержит несколько слов и дополнительный смысл. "
        "Вторая длинная строка содержит несколько слов и дополнительный смысл. "
        "Третья длинная строка содержит несколько слов и дополнительный смысл."
        N8NEmbed.objects.using(alias)
        .filter(tittle__startswith=prefix)
        .order_by("id")
    )
    assert entries
    assert all(len(entry.embeding) == 1536 for entry in entries)


@pytest.mark.django_db(databases="__all__")
def test_process_uploaded_file_fails_for_empty_text(tmp_path):
    empty_path = tmp_path / "empty.txt"
    empty_path.write_text("", encoding="utf-8")

    uploaded = store_uploaded_file(
        chat_id=222,
        file_path=empty_path,
        file_name="empty.txt",
        mime_type="text/plain",
    )

    with pytest.raises(EmptyFileError):
        process_uploaded_file(uploaded, agent=DummyAgent())


@pytest.mark.django_db(databases="__all__")
def test_build_export_archive_contains_original_and_segments(tmp_path):
    text = (
        "Первая длинная строка содержит несколько слов и дополнительный смысл. "
        "Вторая длинная строка содержит несколько слов и дополнительный смысл. "
        "Третья длинная строка содержит несколько слов и дополнительный смысл."
    )
    sample_path = tmp_path / "archive.txt"
    sample_path.write_text(text, encoding="utf-8")

    uploaded = store_uploaded_file(
        chat_id=333,
        file_path=sample_path,
        file_name="archive.txt",
        mime_type="text/plain",
    )

    process_uploaded_file(uploaded, agent=DummyAgent())

    archive_buffer = build_export_archive(uploaded)
    with zipfile.ZipFile(archive_buffer) as archive:
        names = archive.namelist()
        assert f"original/{Path(uploaded.original_file.path).name}" in names
        segments_data = json.loads(archive.read("segments.json"))
        assert segments_data["file_name"] == "archive.txt"
        assert len(segments_data["segments"]) > 0
        assert segments_data["segments"][0]["embeding"] is not None


def test_validate_extension_rejects_unknown_extension():
    with pytest.raises(UnsupportedFormatError):
        validate_extension("file.unsupported")
