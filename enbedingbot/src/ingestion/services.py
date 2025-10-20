from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path
from typing import Iterable, List, Sequence

from django.core.files import File
from django.utils import timezone

from embeddings.agent import EmbeddingAgent
from embeddings.segmenter import segment_text
from ingestion import parsers
from ingestion.constants import MAX_FILE_SIZE_MB, SUPPORTED_EXTENSIONS, UploadStatus
from ingestion.models import UploadedFile
from ingestion.vector_store import VectorStoreService

logger = logging.getLogger(__name__)

TITLE_SEPARATOR = "|"


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
    profile,
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
            profile=profile,
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


def apply_embeddings(
    uploaded: UploadedFile,
    segments: Iterable[str],
    agent: EmbeddingAgent,
    store: VectorStoreService,
) -> None:
    segment_list = list(segments)
    if not segment_list:
        return

    vectors = agent.embed_texts(segment_list)
    if len(vectors) != len(segment_list):
        raise IngestionError("Number of embeddings does not match number of segments.")

    prefix = _title_prefix(uploaded)
    logger.info("Storing %s embeddings for file id=%s", len(vectors), uploaded.id)

    entries: list[tuple[str, str, Sequence[float]]] = [
        (
            _title_for_segment(uploaded, index),
            content,
            vector,
        )
        for index, (content, vector) in enumerate(zip(segment_list, vectors, strict=True), start=1)
    ]
    try:
        store.replace_segments(prefix, entries)
    except Exception as error:  # noqa: BLE001
        logger.exception("Failed to store embeddings for file id=%s", uploaded.id)
        raise IngestionError("Unable to persist embeddings in Supabase.") from error


def process_uploaded_file(uploaded: UploadedFile, agent: EmbeddingAgent | None = None) -> UploadedFile:
    credential = getattr(uploaded.profile, "credential", None)
    if not credential:
        raise IngestionError("Profile is not configured. Run /start and supply Supabase/OpenAI credentials.")

    agent = agent or EmbeddingAgent(api_key=credential.openai_api_key)
    uploaded.status = UploadStatus.PROCESSING.value
    uploaded.error_message = ""
    uploaded.save(update_fields=["status", "error_message"])

    try:
        text = parse_document(uploaded)
        segments = create_segments(uploaded, text)
        store = VectorStoreService(credential)
        apply_embeddings(uploaded, segments, agent, store)
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
    credential = getattr(uploaded.profile, "credential", None)
    if not credential:
        raise IngestionError("Profile is not configured. Run /start first.")

    buffer = io.BytesIO()
    prefix = _title_prefix(uploaded)
    store = VectorStoreService(credential)

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        source_path = Path(uploaded.original_file.path)
        archive.write(source_path, arcname=f"original/{source_path.name}")

        entries = store.fetch_segments(prefix)

        segments_data = [
            {
                "tittle": title,
                "body": body,
                "embeding": list(embedding),
            }
            for title, body, embedding in entries
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
