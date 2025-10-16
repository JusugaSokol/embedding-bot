from __future__ import annotations

from bot.constants import DOWNLOAD_CALLBACK_PREFIX
from bot.keyboards import build_download_keyboard, main_menu_keyboard


def test_main_menu_keyboard_structure():
    keyboard = main_menu_keyboard()
    assert keyboard.resize_keyboard is True
    assert len(keyboard.keyboard) == 2
    assert len(keyboard.keyboard[0]) == 2


def test_build_download_keyboard_creates_callback_with_prefix():
    keyboard = build_download_keyboard([(42, "Test File")])
    assert keyboard.inline_keyboard[0][0].callback_data == f"{DOWNLOAD_CALLBACK_PREFIX}42"
