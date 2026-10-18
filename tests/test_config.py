import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app


def test_settings_use_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EKH_APP_NAME", "Configured Hub")
    monkeypatch.setenv("EKH_ENVIRONMENT", "staging")
    monkeypatch.setenv("EKH_DEBUG", "true")

    settings = Settings(_env_file=None)

    assert settings.app_name == "Configured Hub"
    assert settings.environment == "staging"
    assert settings.debug is True


def test_settings_reject_unknown_environment() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="local", _env_file=None)


def test_settings_require_async_postgresql_driver() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql://localhost/ekh", _env_file=None)


def test_settings_reject_short_jwt_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(jwt_secret="too-short", _env_file=None)


def test_token_expiration_uses_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EKH_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    monkeypatch.setenv("EKH_REFRESH_TOKEN_EXPIRE_DAYS", "14")

    settings = Settings(_env_file=None)

    assert settings.access_token_expire_minutes == 30
    assert settings.refresh_token_expire_days == 14


def test_application_factory_uses_supplied_settings() -> None:
    settings = Settings(app_name="Test Hub", environment="test", _env_file=None)

    application = create_app(settings)

    assert application.title == "Test Hub"
    assert application.state.settings is settings


def test_settings_reject_chunk_overlap_equal_to_chunk_size() -> None:
    with pytest.raises(ValidationError):
        Settings(
            document_chunk_size=100,
            document_chunk_overlap=100,
            _env_file=None,
        )


def test_chunking_settings_use_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EKH_DOCUMENT_CHUNK_SIZE", "800")
    monkeypatch.setenv("EKH_DOCUMENT_CHUNK_OVERLAP", "80")

    settings = Settings(_env_file=None)

    assert settings.document_chunk_size == 800
    assert settings.document_chunk_overlap == 80


def test_vector_settings_use_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EKH_EMBEDDING_MODEL", "custom/model")
    monkeypatch.setenv("EKH_EMBEDDING_DIMENSIONS", "768")
    monkeypatch.setenv("EKH_QDRANT_COLLECTION", "custom_chunks")

    settings = Settings(_env_file=None)

    assert settings.embedding_model == "custom/model"
    assert settings.embedding_dimensions == 768
    assert settings.qdrant_collection == "custom_chunks"


def test_rag_settings_use_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EKH_LLM_MODEL", "custom-llm")
    monkeypatch.setenv("EKH_RAG_MIN_SIMILARITY", "0.72")

    settings = Settings(_env_file=None)

    assert settings.llm_model == "custom-llm"
    assert settings.rag_min_similarity == 0.72


def test_settings_reject_invalid_rag_similarity() -> None:
    with pytest.raises(ValidationError):
        Settings(rag_min_similarity=1.1, _env_file=None)


def test_retrieval_mode_defaults_to_hybrid() -> None:
    settings = Settings(_env_file=None)

    assert settings.retrieval_mode == "hybrid"


def test_retrieval_mode_uses_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EKH_RETRIEVAL_MODE", "lexical")

    settings = Settings(_env_file=None)

    assert settings.retrieval_mode == "lexical"


def test_settings_reject_unknown_retrieval_mode() -> None:
    with pytest.raises(ValidationError):
        Settings(retrieval_mode="weighted", _env_file=None)


def test_rag_pipeline_settings_use_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EKH_QUERY_REWRITING_ENABLED", "true")
    monkeypatch.setenv("EKH_RERANKING_ENABLED", "false")
    monkeypatch.setenv("EKH_RAG_CANDIDATE_COUNT", "30")
    monkeypatch.setenv("EKH_RAG_DEFAULT_TOP_K", "8")

    settings = Settings(_env_file=None)

    assert settings.query_rewriting_enabled is True
    assert settings.reranking_enabled is False
    assert settings.rag_candidate_count == 30
    assert settings.rag_default_top_k == 8


def test_candidate_count_must_cover_default_top_k() -> None:
    with pytest.raises(ValidationError):
        Settings(
            rag_candidate_count=4,
            rag_default_top_k=5,
            _env_file=None,
        )


def test_conversation_history_window_uses_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EKH_CONVERSATION_HISTORY_MESSAGES", "6")

    settings = Settings(_env_file=None)

    assert settings.conversation_history_messages == 6


def test_conversation_history_window_requires_complete_turns() -> None:
    with pytest.raises(ValidationError):
        Settings(conversation_history_messages=3, _env_file=None)


def test_operational_settings_use_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EKH_QUERY_RATE_LIMIT_REQUESTS", "12")
    monkeypatch.setenv("EKH_QUERY_RATE_LIMIT_WINDOW_SECONDS", "90")
    monkeypatch.setenv("EKH_QUERY_EMBEDDING_CACHE_TTL_SECONDS", "600")

    settings = Settings(_env_file=None)

    assert settings.query_rate_limit_requests == 12
    assert settings.query_rate_limit_window_seconds == 90
    assert settings.query_embedding_cache_ttl_seconds == 600


def test_production_rejects_debug_mode() -> None:
    with pytest.raises(ValidationError, match="debug cannot be enabled"):
        Settings(environment="production", debug=True, _env_file=None)


def test_production_rejects_default_object_storage_credentials() -> None:
    with pytest.raises(ValidationError, match="default object storage credentials"):
        Settings(environment="production", _env_file=None)
