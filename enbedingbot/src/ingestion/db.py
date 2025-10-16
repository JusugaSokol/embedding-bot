import os


def get_vector_db_alias() -> str:
    return os.environ.get("INGESTION_VECTOR_ALIAS", "vectors")
