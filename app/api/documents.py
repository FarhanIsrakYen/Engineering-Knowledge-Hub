from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_current_user,
    get_deletable_document_context,
    get_document_context,
    get_ingestion_queue,
    get_object_storage,
    get_vector_store,
    get_workspace_context,
)
from app.db.session import get_db_session
from app.ingestion.queue import IngestionQueue
from app.models.user import User
from app.schemas.document import DocumentResponse
from app.services.documents import (
    create_document,
    delete_document,
    list_workspace_documents,
)
from app.services.tenancy import DocumentContext, WorkspaceContext
from app.storage import ObjectStorage
from app.vector import VectorStore

router = APIRouter(tags=["documents"])


@router.post(
    "/workspaces/{workspace_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    request: Request,
    file: Annotated[UploadFile, File()],
    context: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    ingestion_queue: Annotated[IngestionQueue, Depends(get_ingestion_queue)],
) -> DocumentResponse:
    document = await create_document(
        session,
        storage,
        ingestion_queue,
        context.workspace,
        user,
        file,
        request.app.state.settings.document_max_upload_bytes,
    )
    return DocumentResponse.model_validate(document)


@router.get(
    "/workspaces/{workspace_id}/documents",
    response_model=list[DocumentResponse],
)
async def list_documents(
    context: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[DocumentResponse]:
    documents = await list_workspace_documents(session, context.workspace.id)
    return [DocumentResponse.model_validate(item) for item in documents]


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    context: Annotated[DocumentContext, Depends(get_document_context)],
) -> DocumentResponse:
    return DocumentResponse.model_validate(context.document)


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_document(
    context: Annotated[
        DocumentContext,
        Depends(get_deletable_document_context),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    vector_store: Annotated[VectorStore, Depends(get_vector_store)],
) -> Response:
    await delete_document(session, storage, vector_store, context.document)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
