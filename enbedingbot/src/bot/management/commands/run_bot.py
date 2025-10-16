from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError

from bot.application import build_application


class Command(BaseCommand):
    help = "Запускает Telegram-бота для обработки файлов."

    def handle(self, *args, **options):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
        logger = logging.getLogger(__name__)
        try:
            application = build_application()
        except ValueError as error:
            raise CommandError(str(error)) from error

        logger.info("Бот инициализирован, запускаю polling…")
        self.stdout.write(self.style.SUCCESS("Бот запущен. Нажмите Ctrl+C для остановки."))
        application.run_polling()
