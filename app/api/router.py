from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.conversations import router as conversations_router
from app.api.documents import router as documents_router
from app.api.evaluations import router as evaluations_router
from app.api.health import router as health_router
from app.api.organizations import router as organizations_router
from app.api.query import router as query_router
from app.api.retrieval import router as retrieval_router
from app.api.users import router as users_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(organizations_router)
api_router.include_router(documents_router)
api_router.include_router(evaluations_router)
api_router.include_router(retrieval_router)
api_router.include_router(query_router)
api_router.include_router(conversations_router)
