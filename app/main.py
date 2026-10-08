from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.db.session import create_database_engine, create_session_factory
from app.storage import ObjectStorage, S3ObjectStorage

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    object_storage: ObjectStorage | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = create_database_engine(app_settings.database_url)
        storage = object_storage or S3ObjectStorage(
            endpoint_url=app_settings.object_storage_endpoint_url,
            access_key=app_settings.object_storage_access_key,
            secret_key=app_settings.object_storage_secret_key.get_secret_value(),
            bucket=app_settings.object_storage_bucket,
            region=app_settings.object_storage_region,
        )
        application.state.db_engine = engine
        application.state.db_session_factory = create_session_factory(engine)
        application.state.object_storage = storage
        if app_settings.object_storage_auto_create_bucket:
            await storage.ensure_bucket()
        logger.info(
            "Application started",
            extra={"environment": app_settings.environment},
        )
        try:
            yield
        finally:
            await storage.close()
            await engine.dispose()
            logger.info("Application stopped")

    application = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        debug=app_settings.debug,
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.include_router(health_router, include_in_schema=False)
    application.include_router(api_router, prefix="/api/v1")
    register_exception_handlers(application)
    return application


app = create_app()
