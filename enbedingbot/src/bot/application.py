from __future__ import annotations

from django.conf import settings
from telegram.ext import Application

from bot.handlers import register_handlers


def build_application(token: str | None = None) -> Application:
    resolved_token = token or settings.TELEGRAM_TOKEN
    if not resolved_token:
        raise ValueError("TELEGRAM_TOKEN is missing. Define it in .env.")

    application = Application.builder().token(resolved_token).build()
    register_handlers(application)
    return application
