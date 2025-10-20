from __future__ import annotations

import logging
from typing import Iterable, Sequence

from django.db import connections, transaction
from pgvector.psycopg2 import register_vector

from ingestion.vector_schema import register_vector_connection

logger = logging.getLogger(__name__)


def _ensure_pgvector(cursor) -> None:
    connection = cursor.connection
    if getattr(connection, "_pgvector_registered", False):
        return
    register_vector(connection)
    connection._pgvector_registered = True  # type: ignore[attr-defined]


class VectorStoreService:
    def __init__(self, credential):
        self.credential = credential
        self.table_name = credential.vector_schema_name or "n8n-embed"
        self.alias = register_vector_connection(credential)

    def replace_segments(self, prefix: str, entries: Sequence[tuple[str, str, Sequence[float]]]) -> None:
        logger.info(
            "Replacing %s vector segments in table %s for profile %s",
            len(entries),
            self.table_name,
            self.credential.profile_id,
        )
        with transaction.atomic(using=self.alias):
            self._delete_segments(prefix)
            if entries:
                self._insert_segments(entries)

    def fetch_segments(self, prefix: str) -> list[tuple[str, str, Sequence[float]]]:
        alias = connections[self.alias]
        with alias.cursor() as cursor:
            _ensure_pgvector(cursor)
            cursor.execute(
                f'SELECT tittle, body, embeding FROM "{self.table_name}" WHERE tittle LIKE %s ORDER BY id',
                [f"{prefix}%"],
            )
            rows = cursor.fetchall()
        return [(row[0], row[1], list(row[2])) for row in rows]

    def count_segments(self, prefix: str) -> int:
        alias = connections[self.alias]
        with alias.cursor() as cursor:
            cursor.execute(
                f'SELECT COUNT(*) FROM "{self.table_name}" WHERE tittle LIKE %s',
                [f"{prefix}%"],
            )
            (count,) = cursor.fetchone()
        return int(count)

    def _delete_segments(self, prefix: str) -> None:
        alias = connections[self.alias]
        with alias.cursor() as cursor:
            _ensure_pgvector(cursor)
            cursor.execute(
                f'DELETE FROM "{self.table_name}" WHERE tittle LIKE %s',
                [f"{prefix}%"],
            )

    def _insert_segments(self, entries: Sequence[tuple[str, str, Sequence[float]]]) -> None:
        alias = connections[self.alias]
        with alias.cursor() as cursor:
            _ensure_pgvector(cursor)
            cursor.executemany(
                f'INSERT INTO "{self.table_name}" (tittle, body, embeding) VALUES (%s, %s, %s)',
                entries,
            )
