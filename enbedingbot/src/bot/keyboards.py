from __future__ import annotations

from typing import Iterable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from bot.constants import (
    DOWNLOAD_CALLBACK_PREFIX,
    MAIN_MENU_DOWNLOAD,
    MAIN_MENU_HISTORY,
    MAIN_MENU_UPLOAD,
)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [MAIN_MENU_UPLOAD, MAIN_MENU_HISTORY],
            [MAIN_MENU_DOWNLOAD],
        ],
        resize_keyboard=True,
    )


def build_download_keyboard(items: Iterable[tuple[int, str]]) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=title,
                callback_data=f"{DOWNLOAD_CALLBACK_PREFIX}{file_id}",
            )
        ]
        for file_id, title in items
    ]
    return InlineKeyboardMarkup(buttons)
