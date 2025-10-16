from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import logging

from asgiref.sync import sync_to_async
from django.db.models import QuerySet
from telegram import InputFile, Update
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    logger.info("Получена команда /start от %s", update.effective_chat.id)
    await update.message.reply_text(
        "Привет! Я помогу подготовить файлы к созданию эмбеддингов.\n"
        "Выберите действие на клавиатуре ниже.",
        reply_markup=main_menu_keyboard(),
    )


async def prompt_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    logger.info("Пользователь %s запросил загрузку файла", update.effective_chat.id)
    await update.message.reply_text(
        "Отправьте документ в формате DOCX, CSV, TXT или MD. "
        "Максимальный размер файла — 15 МБ.",
        reply_markup=main_menu_keyboard(),
    )


async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Пользователь %s запросил историю", chat_id)
    files = await _fetch_recent_files(chat_id)
    history_text = format_history(files)
    if update.message:
        await update.message.reply_text(history_text, reply_markup=main_menu_keyboard())


async def show_download_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Пользователь %s запросил выгрузку данных", chat_id)
    files = await _fetch_recent_files(chat_id)
    ready_files = [file for file in files if file.status == UploadStatus.READY.value]
    if not ready_files:
        if update.message:
            await update.message.reply_text(
                "Нет готовых файлов для выгрузки.",
                reply_markup=main_menu_keyboard(),
            )
        return

    keyboard = build_download_keyboard(
        (file.id, f"{file.file_name} ({human_status(file)})") for file in ready_files
    )
    if update.message:
        await update.message.reply_text(
            "Выберите файл, который хотите скачать:",
            reply_markup=keyboard,
        )


async def handle_menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
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
            "Пожалуйста, выберите действие на клавиатуре или отправьте файл.",
            reply_markup=main_menu_keyboard(),
        )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.document:
        return

    document = update.message.document
    chat_id = update.effective_chat.id
    logger.info(
        "Получен документ %s (%s байт) от %s",
        document.file_name,
        document.file_size,
        chat_id,
    )

    try:
        validate_extension(document.file_name)
        validate_file_size(document.file_size or 0)
    except IngestionError as error:
        await update.message.reply_text(str(error), reply_markup=main_menu_keyboard())
        return

    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_path = Path(temp_file.name)
    temp_file.close()

    telegram_file = await document.get_file()
    await telegram_file.download_to_drive(str(temp_path))

    await update.message.reply_text("Файл получен. Начинаю обработку...")

    try:
        uploaded = await sync_to_async(
            store_uploaded_file,
            thread_sensitive=True,
        )(
            chat_id=chat_id,
            file_path=temp_path,
            file_name=document.file_name,
            mime_type=document.mime_type,
        )

        await update.message.reply_text("Файл загружен, разбиваю на сегменты и строю эмбеддинги...")

        await sync_to_async(
            process_uploaded_file,
            thread_sensitive=True,
        )(uploaded)
    except IngestionError as error:
        logger.warning("Не удалось обработать файл %s: %s", document.file_name, error)
        await update.message.reply_text(
            f"Не удалось обработать файл: {error}",
            reply_markup=main_menu_keyboard(),
        )
    else:
        logger.info("Файл %s успешно обработан для пользователя %s", document.file_name, chat_id)
        await update.message.reply_text(
            "Готово! Файл обработан и эмбеддинги сохранены.",
            reply_markup=main_menu_keyboard(),
        )
    finally:
        await asyncio.to_thread(_safe_unlink, temp_path)


async def handle_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    if not query.data.startswith(DOWNLOAD_CALLBACK_PREFIX):
        return

    try:
        file_id = int(query.data[len(DOWNLOAD_CALLBACK_PREFIX) :])
    except ValueError:
        await query.edit_message_text("Некорректный идентификатор файла.")
        return

    chat_id = update.effective_chat.id

    uploaded = await sync_to_async(
        _get_uploaded_file,
        thread_sensitive=True,
    )(file_id=file_id, chat_id=chat_id)

    if not uploaded:
        await query.edit_message_text("Файл не найден или доступ запрещён.")
        return

    if uploaded.status != UploadStatus.READY.value:
        await query.edit_message_text("Файл ещё обрабатывается. Попробуйте позже.")
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
        "Пользователь %s скачивает архив %s (%s сегментов)",
        chat_id,
        zip_name,
        segment_count,
    )
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_document(
        document=InputFile(archive, filename=zip_name),
        caption=f"{uploaded.file_name}: {segment_count} сегментов.",
    )


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_message))
    application.add_handler(CallbackQueryHandler(handle_download_callback, pattern=rf"^{DOWNLOAD_CALLBACK_PREFIX}"))


async def _fetch_recent_files(chat_id: int) -> list[UploadedFile]:
    def _query() -> list[UploadedFile]:
        qs: QuerySet[UploadedFile] = UploadedFile.objects.filter(chat_id=chat_id).order_by("-uploaded_at")[
            :MAX_HISTORY_ITEMS
        ]
        return list(qs)

    return await sync_to_async(_query, thread_sensitive=True)()


def _get_uploaded_file(*, file_id: int, chat_id: int) -> UploadedFile | None:
    try:
        return UploadedFile.objects.get(id=file_id, chat_id=chat_id)
    except UploadedFile.DoesNotExist:
        return None


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except FileNotFoundError:
        return
