from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from bot.models import UserProfile
from ingestion.vector_schema import ensure_vector_schema, register_vector_connection


class Command(BaseCommand):
    help = "Drops and recreates the Supabase vector table for the given Telegram chat id."

    def add_arguments(self, parser):
        parser.add_argument(
            "chat_id",
            type=int,
            help="Telegram chat id of the user whose vector schema must be reset.",
        )

    def handle(self, *args, **options):
        chat_id = options["chat_id"]
        try:
            profile = UserProfile.objects.get(telegram_chat_id=chat_id)
        except UserProfile.DoesNotExist as error:
            raise CommandError(f"Profile with chat id {chat_id} not found.") from error

        credential = getattr(profile, "credential", None)
        if not credential:
            raise CommandError("Profile does not have stored Supabase credentials.")

        alias = register_vector_connection(credential)
        table_name = credential.vector_schema_name

        with connections[alias].cursor() as cursor:
            cursor.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE;')

        ensure_vector_schema(credential)
        self.stdout.write(
            self.style.SUCCESS(
                f"Vector schema '{table_name}' recreated for chat {chat_id} using alias {alias}."
            )
        )
