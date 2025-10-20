from __future__ import annotations

import logging
from typing import Optional

import httpx
import psycopg2
from django.db import transaction
from django.utils import timezone
from openai import AuthenticationError, OpenAI, OpenAIError

from bot.models import UserCredential, UserProfile, UserValidationEvent
from bot.validators import CredentialBundle
from ingestion.vector_schema import ensure_vector_schema

logger = logging.getLogger(__name__)


def _supabase_headers(service_role: Optional[str]) -> dict[str, str]:
    if not service_role:
        return {}
    return {
        "apikey": service_role,
        "Authorization": f"Bearer {service_role}",
    }


def check_vector_database(bundle: CredentialBundle) -> None:
    try:
        with psycopg2.connect(
            dbname=bundle.vector_db_name,
            user=bundle.vector_db_user,
            password=bundle.vector_db_password,
            host=bundle.vector_db_host,
            port=bundle.vector_db_port,
            connect_timeout=5,
            sslmode="require",
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
                cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector';")
    except psycopg2.Error as error:
        logger.warning("Vector database validation failed: %s", error)
        raise ValueError("Unable to connect to Supabase or the 'vector' extension is missing.") from error


def check_supabase_rest(bundle: CredentialBundle) -> None:
    if not bundle.supabase_rest_url or not bundle.supabase_service_role:
        return

    try:
        response = httpx.get(
            str(bundle.supabase_rest_url).rstrip("/") + "/",
            headers=_supabase_headers(bundle.supabase_service_role),
            timeout=5.0,
        )
    except httpx.HTTPError as error:
        logger.warning("Supabase REST validation failed: %s", error)
        raise ValueError("Unable to reach Supabase REST API.") from error

    if response.status_code not in (200, 204):
        raise ValueError(f"Supabase REST API returned status {response.status_code}.")


def check_openai(bundle: CredentialBundle) -> None:
    try:
        client = OpenAI(api_key=bundle.openai_api_key)
        client.embeddings.create(
            model="text-embedding-3-small",
            input="connectivity-check",
        )
    except AuthenticationError as error:
        logger.warning("OpenAI authentication failed: %s", error)
        raise ValueError("OpenAI rejected the supplied API key.") from error
    except OpenAIError as error:
        logger.warning("OpenAI API validation failed: %s", error)
        raise ValueError("OpenAI API call failed. Try again later.") from error


def validate_connectivity(bundle: CredentialBundle) -> None:
    check_vector_database(bundle)
    check_supabase_rest(bundle)
    check_openai(bundle)


def get_or_create_profile(chat_id: int, username: str | None, full_name: str | None) -> UserProfile:
    profile, _ = UserProfile.objects.get_or_create(
        telegram_chat_id=chat_id,
        defaults={
            "telegram_username": username or "",
            "display_name": full_name or "",
        },
    )
    if username and profile.telegram_username != username:
        profile.telegram_username = username
    if full_name and profile.display_name != full_name:
        profile.display_name = full_name
    profile.save()
    return profile


@transaction.atomic
def persist_credentials(profile: UserProfile, bundle: CredentialBundle) -> UserCredential:
    table_name = bundle.vector_schema_name or f"n8n_embed_{profile.id}"
    if table_name == "n8n-embed":
        table_name = f"n8n_embed_{profile.id}"

    profile.phone_number_e164 = bundle.phone_number
    profile.onboarding_completed = True
    profile.save(update_fields=["phone_number_e164", "onboarding_completed", "updated_at"])

    defaults = {
        "supabase_project_id": bundle.supabase_project_id,
        "vector_db_host": bundle.vector_db_host,
        "vector_db_port": bundle.vector_db_port,
        "vector_db_name": bundle.vector_db_name,
        "vector_db_user": bundle.vector_db_user,
        "vector_db_password": bundle.vector_db_password,
        "supabase_rest_url": str(bundle.supabase_rest_url) if bundle.supabase_rest_url else "",
        "supabase_service_role": bundle.supabase_service_role or "",
        "openai_api_key": bundle.openai_api_key,
        "vector_schema_name": table_name,
        "last_validated_at": timezone.now(),
    }

    credential, _ = UserCredential.objects.update_or_create(
        profile=profile,
        defaults=defaults,
    )
    credential.update_openai_fingerprint(bundle.openai_api_key)
    ensure_vector_schema(credential)
    return credential


def record_validation_event(profile: UserProfile, success: bool, context: str, message: str | None = None) -> None:
    UserValidationEvent.objects.create(
        profile=profile,
        success=success,
        context=context,
        message=message or "",
    )
