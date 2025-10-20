from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from asgiref.sync import sync_to_async
from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.keyboards import main_menu_keyboard
from bot.services.onboarding import (
    get_or_create_profile,
    persist_credentials,
    record_validation_event,
    validate_connectivity,
)
from bot.validators import validate_payload

STATE_PHONE = 0
STATE_PROJECT_ID = 1
STATE_DB_HOST = 2
STATE_DB_NAME = 3
STATE_DB_USER = 4
STATE_DB_PASSWORD = 5
STATE_DB_PORT = 6
STATE_SERVICE_ROLE = 7
STATE_REST_URL = 8
STATE_OPENAI_KEY = 9
STATE_VECTOR_TABLE = 10

INFO_MESSAGE = (
    "Привет! Этот бот эмбеддит ваши документы в Supabase с помощью GPT. "
    "Чтобы продолжить, пройдите короткую настройку. В любой момент можно отменить командой /cancel."
)

PHONE_SHARE_LABEL = "Отправить контакт"
SKIP_LABEL = "Пропустить"


@dataclass(frozen=True)
class Step:
    state: int
    field: str
    prompt: str
    optional: bool = False


STEPS: list[Step] = [
    Step(STATE_PHONE, "phone_number", "Введите номер телефона (пример: +79991234567) или нажмите кнопку ниже:"),
    Step(STATE_PROJECT_ID, "supabase_project_id", "Введите идентификатор проекта Supabase (пример: rpxvoqzbjvsthzxmvqrc):"),
    Step(STATE_DB_HOST, "vector_db_host", "Введите хост базы данных Supabase (пример: aws-1-us-east-1.pooler.supabase.com):"),
    Step(STATE_DB_NAME, "vector_db_name", "Введите имя базы данных:"),
    Step(STATE_DB_USER, "vector_db_user", "Введите пользователя базы данных:"),
    Step(STATE_DB_PASSWORD, "vector_db_password", "Введите пароль базы данных:"),
    Step(STATE_DB_PORT, "vector_db_port", "Введите порт базы данных (по умолчанию 5432):"),
    Step(STATE_SERVICE_ROLE, "supabase_service_role", "Введите service role key (опционально, можно пропустить):", optional=True),
    Step(STATE_REST_URL, "supabase_rest_url", "Введите REST URL Supabase (опционально, пример: https://project.supabase.co/rest/v1):", optional=True),
    Step(STATE_OPENAI_KEY, "openai_api_key", "Введите OpenAI API ключ (начинается с sk-):"),
    Step(STATE_VECTOR_TABLE, "vector_schema_name", "Введите название таблицы для эмбеддингов (опционально, Enter для значения по умолчанию):", optional=True),
]

STATE_TO_STEP: dict[int, Step] = {step.state: step for step in STEPS}


def build_onboarding_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            state: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _build_state_handler(state)),
                MessageHandler(filters.CONTACT, _build_state_handler(state)),
            ]
            for state in STATE_TO_STEP
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
        ],
        name="onboarding",
        persistent=False,
    )


def _build_state_handler(state: int):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        return await handle_step(update, context, state)

    return handler


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return ConversationHandler.END

    chat = update.effective_chat
    user = update.effective_user

    profile = await sync_to_async(
        get_or_create_profile,
        thread_sensitive=True,
    )(
        chat_id=chat.id,
        username=user.username,
        full_name=user.full_name,
    )

    context.user_data["profile_id"] = profile.id
    context.user_data["onboarding_data"] = {}

    if profile.onboarding_completed:
        await update.message.reply_text(
            "Настройка уже завершена. Можно загружать документы.",
            reply_markup=main_menu_keyboard(),
        )
        return ConversationHandler.END

    await update.message.reply_text(INFO_MESSAGE, reply_markup=ReplyKeyboardRemove())
    await _send_prompt(update, STEPS[0])
    return STATE_PHONE


async def handle_step(update: Update, context: ContextTypes.DEFAULT_TYPE, state: int):
    if not update.message:
        return state

    message = update.message
    contact = message.contact
    text = (message.text or "").strip()
    step = STATE_TO_STEP[state]

    if step.field == "phone_number":
        if contact and contact.phone_number:
            value = contact.phone_number
        elif text:
            value = text
        else:
            await message.reply_text("Укажите номер телефона вручную или воспользуйтесь кнопкой ниже.")
            await _send_prompt(update, step)
            return state
    elif step.optional and (not text or text.casefold() == SKIP_LABEL.casefold()):
        value = ""
    elif step.field == "vector_db_port":
        if not text:
            value = 5432
        else:
            try:
                value = int(text)
            except ValueError:
                await message.reply_text("Порт должен быть числом.")
                await _send_prompt(update, step)
                return state
    else:
        if not text:
            await message.reply_text("Это поле обязательно. Попробуйте снова.")
            await _send_prompt(update, step)
            return state
        value = text

    context.user_data.setdefault("onboarding_data", {})
    if step.optional and value == "":
        context.user_data["onboarding_data"].pop(step.field, None)
    else:
        context.user_data["onboarding_data"][step.field] = value

    next_state = _next_state(state)
    if next_state is None:
        return await finalize_onboarding(update, context)

    await _send_prompt(update, STATE_TO_STEP[next_state])
    return next_state


def _next_state(current_state: int) -> Optional[int]:
    order = [step.state for step in STEPS]
    try:
        index = order.index(current_state)
    except ValueError:
        return None
    if index + 1 >= len(order):
        return None
    return order[index + 1]


def _prompt_markup(step: Step):
    if step.field == "phone_number":
        button = KeyboardButton(text=PHONE_SHARE_LABEL, request_contact=True)
        return ReplyKeyboardMarkup([[button]], resize_keyboard=True, one_time_keyboard=True)
    if step.optional:
        return ReplyKeyboardMarkup([[SKIP_LABEL]], resize_keyboard=True, one_time_keyboard=True)
    return ReplyKeyboardRemove()


async def _send_prompt(update: Update, step: Step):
    await update.message.reply_text(step.prompt, reply_markup=_prompt_markup(step))


async def finalize_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    data: Dict[str, str | int] = context.user_data.get("onboarding_data", {}).copy()

    rest_url = data.get("supabase_rest_url") or ""
    project_id = data.get("supabase_project_id") or ""
    service_role = data.get("supabase_service_role") or ""
    if not rest_url and service_role and project_id:
        data["supabase_rest_url"] = f"https://{project_id}.supabase.co/rest/v1"

    optional_fields: Iterable[str] = ("supabase_service_role", "supabase_rest_url", "vector_schema_name")
    for field in optional_fields:
        if not data.get(field):
            data.pop(field, None)

    try:
        bundle = validate_payload(data)
    except ValueError as error:
        await update.message.reply_text(
            f"Данные заполнены с ошибками: {error}\nНачнём заново."
        )
        context.user_data["onboarding_data"] = {}
        await _send_prompt(update, STEPS[0])
        return STATE_PHONE

    profile_id = context.user_data.get("profile_id")
    if not profile_id:
        await update.message.reply_text("Не удалось определить профиль. Попробуйте /start снова.")
        return ConversationHandler.END

    profile = await sync_to_async(_get_profile_by_id, thread_sensitive=True)(profile_id)

    try:
        await asyncio.to_thread(validate_connectivity, bundle)
    except ValueError as error:
        await sync_to_async(record_validation_event, thread_sensitive=True)(
            profile,
            False,
            "connectivity",
            str(error),
        )
        await update.message.reply_text(
            f"Проверка подключения не пройдена: {error}\nДавайте попробуем заново."
        )
        context.user_data["onboarding_data"] = {}
        await _send_prompt(update, STEPS[0])
        return STATE_PHONE

    await sync_to_async(record_validation_event, thread_sensitive=True)(
        profile,
        True,
        "connectivity",
        "OK",
    )
    await sync_to_async(persist_credentials, thread_sensitive=True)(profile, bundle)

    await update.message.reply_text(
        "Готово! Подключение сохранено и проверено. Можно загружать документы.",
        reply_markup=main_menu_keyboard(),
    )
    context.user_data.pop("onboarding_data", None)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "Настройка прервана. Вернуться к мастеру можно командой /start.",
            reply_markup=ReplyKeyboardRemove(),
        )
    context.user_data.pop("onboarding_data", None)
    return ConversationHandler.END


def _get_profile_by_id(profile_id: int):
    from bot.models import UserProfile

    return UserProfile.objects.get(id=profile_id)
