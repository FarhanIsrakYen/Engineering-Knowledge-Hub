import logging
from dataclasses import dataclass
from pathlib import PurePath
from typing import BinaryIO
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApplicationError
from app.ingestion.queue import IngestionQueue, IngestionQueueError
from app.models.document import Document
from app.models.user import User
from app.models.workspace import Workspace
from app.storage import ObjectStorage, ObjectStorageError
from app.vector import VectorStore, VectorStoreError

logger = logging.getLogger(__name__)

UPLOAD_CHUNK_SIZE = 1024 * 1024
SUPPORTED_FORMATS: dict[str, tuple[str, frozenset[str]]] = {
    ".pdf": ("application/pdf", frozenset({"application/pdf"})),
    ".md": (
        "text/markdown",
        frozenset({"text/markdown", "text/x-markdown", "text/plain"}),
    ),
    ".markdown": (
        "text/markdown",
        frozenset({"text/markdown", "text/x-markdown", "text/plain"}),
    ),
    ".txt": ("text/plain", frozenset({"text/plain"})),
}


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    original_filename: str
    extension: str
    content_type: str
    size_bytes: int
    file: BinaryIO


async def validate_upload(
    upload: UploadFile,
    max_upload_bytes: int,
) -> ValidatedUpload:
    original_filename = PurePath((upload.filename or "").replace("\\", "/")).name
    if (
        not original_filename
        or len(original_filename) > 255
        or any(ord(character) < 32 for character in original_filename)
    ):
        raise ApplicationError(
            "A valid filename is required",
            code="invalid_file",
            status_code=422,
        )

    extension = PurePath(original_filename).suffix.lower()
    format_config = SUPPORTED_FORMATS.get(extension)
    if format_config is None:
        raise ApplicationError(
            "Unsupported file extension",
            code="unsupported_file_type",
            status_code=415,
        )

    canonical_content_type, accepted_content_types = format_config
    supplied_content_type = (upload.content_type or "").split(";", 1)[0].lower()
    if supplied_content_type not in accepted_content_types:
        raise ApplicationError(
            "File content type does not match its extension",
            code="unsupported_file_type",
            status_code=415,
        )

    size_bytes = 0
    while chunk := await upload.read(UPLOAD_CHUNK_SIZE):
        size_bytes += len(chunk)
        if size_bytes > max_upload_bytes:
            raise ApplicationError(
                "File exceeds the maximum upload size",
                code="file_too_large",
                status_code=413,
            )

    if size_bytes == 0:
        raise ApplicationError(
            "Empty files are not allowed",
            code="empty_file",
            status_code=422,
        )

    await upload.seek(0)
    return ValidatedUpload(
        original_filename=original_filename,
        extension=extension,
        content_type=canonical_content_type,
        size_bytes=size_bytes,
        file=upload.file,
    )


async def create_document(
    session: AsyncSession,
    storage: ObjectStorage,
    ingestion_queue: IngestionQueue,
    workspace: Workspace,
    user: User,
    upload: UploadFile,
    max_upload_bytes: int,
) -> Document:
    validated = await validate_upload(upload, max_upload_bytes)
    document_id = uuid4()
    storage_key = (
        f"organizations/{workspace.organization_id}/workspaces/{workspace.id}/"
        f"documents/{document_id}{validated.extension}"
    )

    try:
        await storage.upload_file(
            storage_key,
            validated.file,
            validated.content_type,
        )
    except ObjectStorageError as exc:
        raise ApplicationError(
            "Object storage is unavailable",
            code="object_storage_unavailable",
            status_code=503,
        ) from exc

    document = Document(
        id=document_id,
        workspace_id=workspace.id,
        original_filename=validated.original_filename,
        content_type=validated.content_type,
        storage_key=storage_key,
        size_bytes=validated.size_bytes,
        status="pending",
        created_by=user.id,
    )
    session.add(document)
    try:
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        try:
            await storage.delete_file(storage_key)
        except ObjectStorageError:
            logger.exception("Failed to clean up object after metadata error")
        raise ApplicationError(
            "Document metadata could not be saved",
            code="document_create_failed",
            status_code=500,
        ) from exc

    await session.refresh(document)
    try:
        await ingestion_queue.enqueue(document.id)
    except IngestionQueueError as exc:
        document.status = "failed"
        document.failure_reason = "Document ingestion could not be queued"
        await session.commit()
        raise ApplicationError(
            "Document ingestion could not be queued",
            code="ingestion_queue_unavailable",
            status_code=503,
        ) from exc
    return document


async def list_workspace_documents(
    session: AsyncSession,
    workspace_id: UUID,
) -> list[Document]:
    documents = await session.scalars(
        select(Document)
        .where(Document.workspace_id == workspace_id)
        .order_by(Document.created_at, Document.id)
    )
    return list(documents)


async def delete_document(
    session: AsyncSession,
    storage: ObjectStorage,
    vector_store: VectorStore,
    document: Document,
) -> None:
    try:
        await vector_store.delete_document_vectors(document.id)
    except VectorStoreError as exc:
        raise ApplicationError(
            "Vector store is unavailable",
            code="vector_store_unavailable",
            status_code=503,
        ) from exc
    try:
        await storage.delete_file(document.storage_key)
    except ObjectStorageError as exc:
        raise ApplicationError(
            "Object storage is unavailable",
            code="object_storage_unavailable",
            status_code=503,
        ) from exc

    await session.delete(document)
    await session.commit()
