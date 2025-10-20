from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from asgiref.sync import sync_to_async
from django.db.models import QuerySet
from telegram import InputFile, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.constants import (
    DOWNLOAD_CALLBACK_PREFIX,
    MAIN_MENU_DOWNLOAD,
    MAIN_MENU_HISTORY,
    MAIN_MENU_UPLOAD,
    MAX_HISTORY_ITEMS,
)
from bot.keyboards import build_download_keyboard, main_menu_keyboard
from bot.models import UserProfile
from bot.onboarding import build_onboarding_handler
from bot.utils import format_history, human_status
from ingestion.constants import UploadStatus
from ingestion.models import UploadedFile
from ingestion.services import (
    IngestionError,
    build_export_archive,
    process_uploaded_file,
    store_uploaded_file,
    validate_extension,
    validate_file_size,
)

logger = logging.getLogger(__name__)


async def _load_profile(chat_id: int) -> UserProfile | None:
    def _query() -> UserProfile | None:
        return (
            UserProfile.objects.select_related("credential")
            .filter(telegram_chat_id=chat_id)
            .first()
        )

    return await sync_to_async(_query, thread_sensitive=True)()


async def _require_onboarding(update: Update) -> UserProfile | None:
    profile = await _load_profile(update.effective_chat.id)
    if profile and profile.onboarding_completed:
        return profile

    message = (
        "Setup is not finished yet. Run /start and complete the onboarding wizard first."
    )
    if update.message:
        await update.message.reply_text(message, reply_markup=ReplyKeyboardRemove())
    elif update.callback_query:
        await update.callback_query.edit_message_text(message)
    return None


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile = await _require_onboarding(update)
    if not profile or not update.message:
        return
    await update.message.reply_text(
        "Choose what to do next:",
        reply_markup=main_menu_keyboard(),
    )


async def prompt_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    profile = await _require_onboarding(update)
    if not profile:
        return

    logger.info("Chat %s requested upload prompt", update.effective_chat.id)
    await update.message.reply_text(
        "Send a DOCX, CSV, TXT, or Markdown file up to 15 MB.",
        reply_markup=main_menu_keyboard(),
    )


async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    profile = await _require_onboarding(update)
    if not profile:
        return

    logger.info("Chat %s requested history", update.effective_chat.id)
    files = await _fetch_recent_files(profile)
    history_text = format_history(files)
    await update.message.reply_text(history_text, reply_markup=main_menu_keyboard())


async def show_download_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    profile = await _require_onboarding(update)
    if not profile:
        return

    logger.info("Chat %s requested download options", update.effective_chat.id)
    files = await _fetch_recent_files(profile)
    ready_files = [file for file in files if file.status == UploadStatus.READY.value]

    if not ready_files:
        await update.message.reply_text(
            "No ready exports yet.",
            reply_markup=main_menu_keyboard(),
        )
        return

    keyboard = build_download_keyboard(
        (file.id, f"{file.file_name} ({human_status(file)})") for file in ready_files
    )
    await update.message.reply_text(
        "Select the file to download:",
        reply_markup=keyboard,
    )


async def handle_menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    profile = await _require_onboarding(update)
    if not profile:
        return

    text = (update.message.text or "").strip()
    if text == MAIN_MENU_UPLOAD:
        await prompt_upload(update, context)
    elif text == MAIN_MENU_HISTORY:
        await show_history(update, context)
    elif text == MAIN_MENU_DOWNLOAD:
        await show_download_options(update, context)
    else:
        await update.message.reply_text(
            "Use the keyboard buttons to continue.",
            reply_markup=main_menu_keyboard(),
        )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.document:
        return

    profile = await _require_onboarding(update)
    if not profile:
        return

    document = update.message.document
    chat_id = update.effective_chat.id
    logger.info("Chat %s uploaded document %s", chat_id, document.file_name)

    temp_path: Path | None = None
    try:
        if document.file_name:
            validate_extension(document.file_name)
        if document.file_size is not None:
            validate_file_size(document.file_size)

        file = await document.get_file()
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_path = Path(temp_file.name)
        await asyncio.to_thread(file.download_to_drive, custom_path=str(temp_path))

        uploaded = await sync_to_async(
            store_uploaded_file,
            thread_sensitive=True,
        )(
            profile=profile,
            chat_id=chat_id,
            file_path=temp_path,
            file_name=document.file_name or "",
            mime_type=document.mime_type,
        )

        await update.message.reply_text(
            "File received. Processing with GPT embeddings..."
        )

        await sync_to_async(
            process_uploaded_file,
            thread_sensitive=True,
        )(uploaded)
    except IngestionError as error:
        logger.warning("Failed to process %s: %s", document.file_name, error)
        await update.message.reply_text(
            f"Processing failed: {error}",
            reply_markup=main_menu_keyboard(),
        )
    else:
        logger.info("Document %s processed for chat %s", document.file_name, chat_id)
        await update.message.reply_text(
            "Done! The document is embedded and ready for download.",
            reply_markup=main_menu_keyboard(),
        )
    finally:
        if temp_path:
            await asyncio.to_thread(_safe_unlink, temp_path)


async def handle_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    if not query.data.startswith(DOWNLOAD_CALLBACK_PREFIX):
        return

    profile = await _require_onboarding(update)
    if not profile:
        return

    try:
        file_id = int(query.data[len(DOWNLOAD_CALLBACK_PREFIX) :])
    except ValueError:
        await query.edit_message_text("Unknown file.")
        return

    uploaded = await sync_to_async(
        _get_uploaded_file,
        thread_sensitive=True,
    )(file_id=file_id, profile=profile)

    if not uploaded:
        await query.edit_message_text("File not found.")
        return

    if uploaded.status != UploadStatus.READY.value:
        await query.edit_message_text("File is still processing. Try again later.")
        return

    archive = await sync_to_async(
        build_export_archive,
        thread_sensitive=True,
    )(uploaded)

    segment_count = await sync_to_async(
        uploaded.segments_count,
        thread_sensitive=True,
    )()

    zip_name = f"{Path(uploaded.file_name).stem or 'export'}.zip"
    logger.info(
        "Chat %s downloading archive %s (%s segments)",
        update.effective_chat.id,
        zip_name,
        segment_count,
    )
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_document(
        document=InputFile(archive, filename=zip_name),
        caption=f"{uploaded.file_name}: {segment_count} segments.",
    )


def register_handlers(application: Application) -> None:
    application.add_handler(build_onboarding_handler())
    application.add_handler(CommandHandler("menu", show_menu))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_message))
    application.add_handler(CallbackQueryHandler(handle_download_callback, pattern=rf"^{DOWNLOAD_CALLBACK_PREFIX}"))


async def _fetch_recent_files(profile: UserProfile) -> list[UploadedFile]:
    def _query() -> list[UploadedFile]:
        qs: QuerySet[UploadedFile] = (
            UploadedFile.objects.filter(profile=profile)
            .order_by("-uploaded_at")[:MAX_HISTORY_ITEMS]
        )
        return list(qs)

    return await sync_to_async(_query, thread_sensitive=True)()


def _get_uploaded_file(*, file_id: int, profile: UserProfile) -> UploadedFile | None:
    try:
        return UploadedFile.objects.get(id=file_id, profile=profile)
    except UploadedFile.DoesNotExist:
        return None


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except FileNotFoundError:
        return
