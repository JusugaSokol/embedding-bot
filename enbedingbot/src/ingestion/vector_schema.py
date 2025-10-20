from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import connections

if TYPE_CHECKING:  # pragma: no cover
    from bot.models import UserCredential

logger = logging.getLogger(__name__)


def vector_alias_for_profile(profile_id: int) -> str:
    return f"user_{profile_id}_vectors"


def register_vector_connection(credential: "UserCredential") -> str:
    alias = vector_alias_for_profile(credential.profile_id)
    if alias in connections.databases:
        return alias

    connections.databases[alias] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": credential.vector_db_name,
        "USER": credential.vector_db_user,
        "PASSWORD": credential.vector_db_password,
        "HOST": credential.vector_db_host,
        "PORT": credential.vector_db_port,
        "OPTIONS": {
            "sslmode": "require",
        },
    }
    logger.info("Registered vector connection alias %s for profile %s", alias, credential.profile_id)
    return alias


def ensure_vector_schema(credential: "UserCredential") -> str:
    alias = register_vector_connection(credential)
    table_name = credential.vector_schema_name or "n8n-embed"

    with connections[alias].cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS "{table_name}" (
                id bigserial PRIMARY KEY,
                tittle varchar(255) NOT NULL,
                body text NOT NULL,
                embeding vector(1536) NOT NULL
            );
            """
        )
    logger.info(
        "Ensured vector table %s exists for profile %s using alias %s",
        table_name,
        credential.profile_id,
        alias,
    )
    return alias
