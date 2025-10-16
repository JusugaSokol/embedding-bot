from __future__ import annotations

from typing import Optional

from ingestion.db import get_vector_db_alias


class EmbeddingRouter:
    app_label = "ingestion"
    vector_models = {"n8nembed"}

    def _is_vector_model(self, model) -> bool:
        return model._meta.app_label == self.app_label and model._meta.model_name in self.vector_models

    def _is_ingestion_model(self, model) -> bool:
        return model._meta.app_label == self.app_label

    def db_for_read(self, model, **hints) -> Optional[str]:
        if self._is_vector_model(model):
            return get_vector_db_alias()
        if self._is_ingestion_model(model):
            return "default"
        return None

    def db_for_write(self, model, **hints) -> Optional[str]:
        return self.db_for_read(model, **hints)

    def allow_relation(self, obj1, obj2, **hints) -> bool | None:
        alias = get_vector_db_alias()
        db_list = {"default", alias}
        if (
            obj1._state.db in db_list
            and obj2._state.db in db_list
        ):
            return True
        return None

    def allow_migrate(self, db: str, app_label: str, model_name: Optional[str] = None, **hints) -> Optional[bool]:
        if app_label != self.app_label:
            return None

        if model_name in self.vector_models:
            return db == get_vector_db_alias()

        if model_name:
            return db == "default"

        operation = hints.get("operation")
        if operation and operation.__class__.__name__ == "VectorExtension":
            return db == get_vector_db_alias()

        return db == "default"
