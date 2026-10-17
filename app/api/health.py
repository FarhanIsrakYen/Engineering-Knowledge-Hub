from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.health import HealthResponse, ReadinessResponse
from app.services.readiness import (
    verify_database_connection,
    verify_ingestion_queue,
    verify_object_storage,
    verify_redis,
    verify_vector_store,
)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReadinessResponse:
    await verify_database_connection(session)
    await verify_object_storage(request.app.state.object_storage)
    await verify_ingestion_queue(request.app.state.ingestion_queue)
    await verify_vector_store(request.app.state.vector_store)
    await verify_redis(request.app.state.redis)
    return ReadinessResponse(
        status="ready",
        checks={
            "database": "ok",
            "object_storage": "ok",
            "ingestion_queue": "ok",
            "vector_store": "ok",
            "redis": "ok",
        },
    )
