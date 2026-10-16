from functools import lru_cache
from typing import Literal

from pydantic import (
    Field,
    NonNegativeInt,
    PositiveInt,
    SecretStr,
    field_validator,
    model_validator,
)
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
    redis_url: str = "redis://localhost:6379/0"
    document_chunk_size: PositiveInt = 1200
    document_chunk_overlap: NonNegativeInt = 150
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimensions: PositiveInt = 384
    embedding_cache_dir: str | None = None
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "document_chunks_v1"
    qdrant_auto_initialize: bool = False
    retrieval_mode: Literal["vector", "lexical", "hybrid"] = "hybrid"
    query_rewriting_enabled: bool = False
    reranking_enabled: bool = True
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    reranker_cache_dir: str | None = None
    rag_candidate_count: int = Field(default=20, ge=1, le=50)
    rag_default_top_k: int = Field(default=5, ge=1, le=20)
    llm_api_key: SecretStr | None = None
    llm_model: str = "gpt-5.5"
    llm_base_url: str | None = None
    llm_timeout_seconds: PositiveInt = 30
    llm_max_output_tokens: PositiveInt = 800
    rag_min_similarity: float = Field(default=0.5, ge=-1.0, le=1.0)

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

    @field_validator("redis_url")
    @classmethod
    def require_redis_url(cls, value: str) -> str:
        if not value.startswith(("redis://", "rediss://")):
            raise ValueError("redis_url must use the redis or rediss scheme")
        return value

    @field_validator(
        "embedding_model",
        "qdrant_collection",
        "llm_model",
        "reranker_model",
    )
    @classmethod
    def require_nonempty_vector_setting(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("vector configuration values cannot be empty")
        return value

    @field_validator("llm_api_key", mode="before")
    @classmethod
    def normalize_empty_llm_api_key(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("llm_base_url", mode="before")
    @classmethod
    def normalize_empty_llm_base_url(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("llm_base_url")
    @classmethod
    def require_llm_base_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError("llm_base_url must use the http or https scheme")
        return value

    @field_validator("qdrant_url")
    @classmethod
    def require_qdrant_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("qdrant_url must use the http or https scheme")
        return value

    @model_validator(mode="after")
    def validate_chunking_settings(self) -> "Settings":
        if self.document_chunk_overlap >= self.document_chunk_size:
            raise ValueError(
                "document_chunk_overlap must be smaller than document_chunk_size"
            )
        if self.rag_default_top_k > self.rag_candidate_count:
            raise ValueError(
                "rag_default_top_k cannot exceed rag_candidate_count"
            )
        return self

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
