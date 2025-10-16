from __future__ import annotations

import io
import json
import logging
import time
import zipfile
from pathlib import Path
from typing import Callable, Iterable, List, TypeVar

from django.core.files import File
from django.db import OperationalError, connections, transaction
from django.utils import timezone

from embeddings.agent import EmbeddingAgent
from embeddings.segmenter import segment_text
from ingestion import parsers
from ingestion.constants import MAX_FILE_SIZE_MB, SUPPORTED_EXTENSIONS, UploadStatus
from ingestion.db import get_vector_db_alias
from ingestion.models import N8NEmbed, UploadedFile

logger = logging.getLogger(__name__)

TITLE_SEPARATOR = "|"
DB_MAX_RETRIES = 3
DB_RETRY_DELAY_SECONDS = 1.0
DB_STEP_DELAY_SECONDS = 0.25
T = TypeVar("T")


class IngestionError(Exception):
    """Base class for ingestion errors."""


class UnsupportedFormatError(IngestionError):
    """Raised when the uploaded file has an unsupported extension."""


class EmptyFileError(IngestionError):
    """Raised when the uploaded file contains no text after parsing."""


class FileTooLargeError(IngestionError):
    """Raised when the uploaded file exceeds the size limit."""


def _title_prefix(uploaded: UploadedFile) -> str:
    return f"{uploaded.file_name}{TITLE_SEPARATOR}{uploaded.id}{TITLE_SEPARATOR}"


def _title_for_segment(uploaded: UploadedFile, position: int) -> str:
    return f"{_title_prefix(uploaded)}{position}"


def _execute_with_retry(alias: str, func: Callable[[], T]) -> T:
    for attempt in range(1, DB_MAX_RETRIES + 1):
        try:
            return func()
        except OperationalError as error:
            logger.warning(
                "Database operation failed (attempt %s/%s): %s",
                attempt,
                DB_MAX_RETRIES,
                error,
            )
            connections[alias].close()
            if attempt == DB_MAX_RETRIES:
                raise
            time.sleep(DB_RETRY_DELAY_SECONDS * attempt)
    raise IngestionError("Database operation failed after retries.")


def validate_extension(file_name: str) -> None:
    extension = Path(file_name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"File format {extension or 'without extension'} is not supported."
        )


def validate_file_size(file_size: int) -> None:
    max_size_bytes = MAX_FILE_SIZE_MB * 1_024 * 1_024
    if file_size > max_size_bytes:
        raise FileTooLargeError(f"File size exceeds {MAX_FILE_SIZE_MB} MB.")


def store_uploaded_file(
    *,
    chat_id: int,
    file_path: Path,
    file_name: str,
    mime_type: str | None = None,
) -> UploadedFile:
    validate_extension(file_name)
    file_size = file_path.stat().st_size
    validate_file_size(file_size)

    logger.info("Received file %s (%s bytes) from chat %s", file_name, file_size, chat_id)

    with file_path.open("rb") as source:
        django_file = File(source, name=file_name)
        uploaded = UploadedFile.objects.create(
            chat_id=chat_id,
            file_name=file_name,
            file_size=file_size,
            mime_type=mime_type or "",
            status=UploadStatus.PENDING.value,
        )
        uploaded.original_file.save(file_name, django_file, save=True)

    return uploaded


def parse_document(uploaded: UploadedFile) -> str:
    source_path = Path(uploaded.original_file.path)
    logger.info("Parsing file %s (id=%s)", uploaded.file_name, uploaded.id)
    text = parsers.extract_text(source_path)
    if not text.strip():
        raise EmptyFileError("No text found in file after processing.")
    logger.info("Parsed %s characters", len(text))
    return text


def create_segments(uploaded: UploadedFile, text: str) -> List[str]:
    segments = segment_text(text)
    if not segments:
        raise EmptyFileError("Unable to split text into segments.")

    logger.info("Generated %s segments for file id=%s", len(segments), uploaded.id)
    return segments


def apply_embeddings(uploaded: UploadedFile, segments: Iterable[str], agent: EmbeddingAgent) -> None:
    segment_list = list(segments)
    if not segment_list:
        return

    vectors = agent.embed_texts(segment_list)
    if len(vectors) != len(segment_list):
        raise IngestionError("Number of embeddings does not match number of segments.")

    alias = get_vector_db_alias()
    prefix = _title_prefix(uploaded)
    logger.info("Storing %s embeddings for file id=%s", len(vectors), uploaded.id)

    def _delete_existing() -> None:
        with transaction.atomic(using=alias):
            N8NEmbed.objects.using(alias).filter(tittle__startswith=prefix).delete()

    _execute_with_retry(alias, _delete_existing)
    time.sleep(DB_STEP_DELAY_SECONDS)

    entries = [
        N8NEmbed(
            tittle=_title_for_segment(uploaded, index),
            body=content,
            embeding=vector,
        )
        for index, (content, vector) in enumerate(zip(segment_list, vectors, strict=True), start=1)
    ]

    def _insert_entries() -> None:
        with transaction.atomic(using=alias):
            N8NEmbed.objects.using(alias).bulk_create(entries)

    _execute_with_retry(alias, _insert_entries)
    time.sleep(DB_STEP_DELAY_SECONDS)


def process_uploaded_file(uploaded: UploadedFile, agent: EmbeddingAgent | None = None) -> UploadedFile:
    agent = agent or EmbeddingAgent()
    uploaded.status = UploadStatus.PROCESSING.value
    uploaded.error_message = ""
    uploaded.save(update_fields=["status", "error_message"])

    try:
        text = parse_document(uploaded)
        segments = create_segments(uploaded, text)
        apply_embeddings(uploaded, segments, agent)
    except IngestionError as error:
        logger.warning("Processing of file id=%s failed: %s", uploaded.id, error)
        uploaded.status = UploadStatus.FAILED.value
        uploaded.error_message = str(error)
        uploaded.processed_at = timezone.now()
        uploaded.save(update_fields=["status", "error_message", "processed_at"])
        raise
    except Exception as error:  # noqa: BLE001
        uploaded.status = UploadStatus.FAILED.value
        uploaded.error_message = str(error)
        uploaded.processed_at = timezone.now()
        uploaded.save(update_fields=["status", "error_message", "processed_at"])
        logger.exception("Unexpected error while processing file id=%s", uploaded.id)
        raise IngestionError("Unable to process file. Please try again later.") from error
    else:
        uploaded.status = UploadStatus.READY.value
        uploaded.processed_at = timezone.now()
        uploaded.save(update_fields=["status", "processed_at", "error_message"])
        logger.info("File id=%s processed successfully", uploaded.id)
        return uploaded


def build_export_archive(uploaded: UploadedFile) -> io.BytesIO:
    buffer = io.BytesIO()
    alias = get_vector_db_alias()
    prefix = _title_prefix(uploaded)

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        source_path = Path(uploaded.original_file.path)
        archive.write(source_path, arcname=f"original/{source_path.name}")

        def _fetch_entries() -> list[N8NEmbed]:
            return list(
                N8NEmbed.objects.using(alias)
                .filter(tittle__startswith=prefix)
                .order_by("id")
            )

        entries = _execute_with_retry(alias, _fetch_entries)

        segments_data = [
            {
                "tittle": entry.tittle,
                "body": entry.body,
                "embeding": entry.embeding,
            }
            for entry in entries
        ]
        archive.writestr(
            "segments.json",
            json.dumps(
                {
                    "file_name": uploaded.file_name,
                    "chat_id": uploaded.chat_id,
                    "status": uploaded.status,
                    "segments": segments_data,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    buffer.seek(0)
    return buffer
