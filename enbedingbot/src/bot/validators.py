from __future__ import annotations

import re
from typing import Optional

import phonenumbers
from pydantic import AnyUrl, BaseModel, Field, ValidationError, field_validator


class CredentialBundle(BaseModel):
    phone_number: str = Field(min_length=1)
    supabase_project_id: str = Field(min_length=4, max_length=150)
    vector_db_host: str = Field(min_length=3, max_length=255)
    vector_db_name: str = Field(min_length=1, max_length=128)
    vector_db_user: str = Field(min_length=1, max_length=128)
    vector_db_password: str = Field(min_length=1)
    vector_db_port: int = Field(default=5432, ge=1, le=65535)
    supabase_service_role: Optional[str] = None
    supabase_rest_url: Optional[AnyUrl] = None
    openai_api_key: str = Field(min_length=10)
    vector_schema_name: str = Field(min_length=1, max_length=128, default="n8n-embed")

    model_config = {"extra": "ignore"}

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        try:
            parsed = phonenumbers.parse(value, None)
        except phonenumbers.NumberParseException as error:
            raise ValueError(str(error)) from error
        if not phonenumbers.is_valid_number(parsed):
            raise ValueError("Phone number is not valid.")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

    @field_validator("vector_db_host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        normalized = value.strip()
        if "." not in normalized:
            raise ValueError("Host must include a domain.")
        return normalized

    @field_validator("vector_db_name", "vector_db_user", "vector_schema_name")
    @classmethod
    def ensure_no_spaces(cls, value: str) -> str:
        if " " in value:
            raise ValueError("Value must not contain spaces.")
        return value.strip()

    @field_validator("vector_db_password")
    @classmethod
    def ensure_password(cls, value: str) -> str:
        if len(value) < 6:
            raise ValueError("Password must be at least 6 characters.")
        return value

    @field_validator("supabase_project_id")
    @classmethod
    def normalize_project(cls, value: str) -> str:
        return value.strip()

    @field_validator("supabase_service_role")
    @classmethod
    def normalize_service_role(cls, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        return value.strip()

    @field_validator("supabase_rest_url")
    @classmethod
    def normalize_rest_url(cls, value: Optional[AnyUrl]) -> Optional[AnyUrl]:
        return value

    @field_validator("openai_api_key")
    @classmethod
    def validate_openai_key(cls, value: str) -> str:
        key = value.strip()
        if not re.match(r"^sk-[a-zA-Z0-9\-]{20,}$", key):
            raise ValueError("OpenAI key must start with 'sk-' and contain at least 20 characters.")
        return key


def validate_payload(data: dict) -> CredentialBundle:
    try:
        return CredentialBundle(**data)
    except ValidationError as error:
        errors = ", ".join(detail["msg"] for detail in error.errors())
        raise ValueError(errors) from error
