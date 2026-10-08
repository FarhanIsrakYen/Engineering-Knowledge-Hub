from functools import lru_cache
from typing import Literal

from pydantic import PositiveInt, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Engineering Knowledge Hub"
    environment: Literal["development", "test", "staging", "production"] = (
        "development"
    )
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str = "postgresql+asyncpg://ekh:ekh@localhost:5432/ekh"
    jwt_secret: SecretStr
    access_token_expire_minutes: PositiveInt = 15
    refresh_token_expire_days: PositiveInt = 7
    jwt_issuer: str = "engineering-knowledge-hub"
    jwt_audience: str = "engineering-knowledge-hub-api"
    object_storage_endpoint_url: str = "http://localhost:9000"
    object_storage_access_key: str = "minioadmin"
    object_storage_secret_key: SecretStr = SecretStr("minioadmin")
    object_storage_bucket: str = "engineering-knowledge-hub"
    object_storage_region: str = "us-east-1"
    object_storage_auto_create_bucket: bool = False
    document_max_upload_bytes: PositiveInt = 25 * 1024 * 1024

    @field_validator("database_url")
    @classmethod
    def require_async_postgresql_url(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("database_url must use the postgresql+asyncpg driver")
        return value

    @field_validator("jwt_secret")
    @classmethod
    def require_strong_jwt_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("jwt_secret must contain at least 32 characters")
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="EKH_",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
