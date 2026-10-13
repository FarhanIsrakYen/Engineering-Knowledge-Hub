import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app


def test_settings_use_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EKH_APP_NAME", "Configured Hub")
    monkeypatch.setenv("EKH_ENVIRONMENT", "production")
    monkeypatch.setenv("EKH_DEBUG", "true")

    settings = Settings(_env_file=None)

    assert settings.app_name == "Configured Hub"
    assert settings.environment == "production"
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
