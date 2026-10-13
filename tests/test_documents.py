from collections.abc import Iterator
from dataclasses import dataclass
import os
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings
from app.main import create_app
from tests.storage import InMemoryObjectStorage
from tests.queue import InMemoryIngestionQueue
from tests.vector_store import InMemoryVectorStore


@dataclass(frozen=True, slots=True)
class DocumentTestContext:
    client: TestClient
    storage: InMemoryObjectStorage
    queue: InMemoryIngestionQueue
    vector_store: InMemoryVectorStore


@pytest.fixture
def document_context() -> Iterator[DocumentTestContext]:
    database_url = os.getenv("EKH_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("EKH_TEST_DATABASE_URL is required for document tests")

    storage = InMemoryObjectStorage()
    queue = InMemoryIngestionQueue()
    vector_store = InMemoryVectorStore()
    settings = Settings(
        environment="test",
        database_url=database_url,
        jwt_secret="test-only-jwt-secret-with-at-least-32-characters",
        document_max_upload_bytes=64,
        _env_file=None,
    )
    with TestClient(
        create_app(
            settings,
            object_storage=storage,
            ingestion_queue=queue,
            vector_store=vector_store,
        )
    ) as test_client:
        yield DocumentTestContext(
            client=test_client,
            storage=storage,
            queue=queue,
            vector_store=vector_store,
        )


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_user_and_token(client: TestClient, label: str) -> tuple[str, str]:
    email = f"{label}-{uuid4().hex}@example.com"
    password = "correct horse battery staple"
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": label.title()},
    )
    assert registration.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
    return email, login.json()["access_token"]


def create_workspace(client: TestClient, token: str, label: str) -> str:
    organization = client.post(
        "/api/v1/organizations",
        headers=auth_headers(token),
        json={"name": f"{label} Organization", "slug": f"{label}-{uuid4().hex}"},
    )
    assert organization.status_code == 201
    workspace = client.post(
        f"/api/v1/organizations/{organization.json()['id']}/workspaces",
        headers=auth_headers(token),
        json={"name": f"{label} Workspace"},
    )
    assert workspace.status_code == 201
    return workspace.json()["id"]


def upload_markdown(client: TestClient, token: str, workspace_id: str):
    return client.post(
        f"/api/v1/workspaces/{workspace_id}/documents",
        headers=auth_headers(token),
        files={"file": ("notes.md", b"# Engineering notes", "text/markdown")},
    )


@pytest.mark.integration
def test_upload_creates_pending_metadata_and_stores_bytes(
    document_context: DocumentTestContext,
) -> None:
    client = document_context.client
    _, token = create_user_and_token(client, "uploader")
    workspace_id = create_workspace(client, token, "upload")

    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/documents",
        headers=auth_headers(token),
        files={
            "file": (
                "../../Quarterly Notes.md",
                b"# Quarterly engineering notes",
                "text/markdown",
            )
        },
    )

    assert response.status_code == 202
    document = response.json()
    assert document["original_filename"] == "Quarterly Notes.md"
    assert document["content_type"] == "text/markdown"
    assert document["size_bytes"] == len(b"# Quarterly engineering notes")
    assert document["status"] == "pending"
    assert document["failure_reason"] is None
    assert "Quarterly Notes.md" not in document["storage_key"]
    assert document["storage_key"] in document_context.storage.objects
    assert document_context.storage.objects[document["storage_key"]][0] == (
        b"# Quarterly engineering notes"
    )
    assert str(document_context.queue.document_ids[-1]) == document["id"]

    list_response = client.get(
        f"/api/v1/workspaces/{workspace_id}/documents",
        headers=auth_headers(token),
    )
    get_response = client.get(
        f"/api/v1/documents/{document['id']}",
        headers=auth_headers(token),
    )
    assert list_response.status_code == 200
    assert document["id"] in {item["id"] for item in list_response.json()}
    assert get_response.status_code == 200
    assert get_response.json() == document


@pytest.mark.integration
@pytest.mark.parametrize(
    ("filename", "content", "content_type", "status_code", "error_code"),
    [
        ("malware.exe", b"payload", "application/octet-stream", 415, "unsupported_file_type"),
        ("manual.pdf", b"not a pdf", "text/plain", 415, "unsupported_file_type"),
        ("empty.txt", b"", "text/plain", 422, "empty_file"),
        ("large.txt", b"x" * 65, "text/plain", 413, "file_too_large"),
    ],
)
def test_upload_validation(
    document_context: DocumentTestContext,
    filename: str,
    content: bytes,
    content_type: str,
    status_code: int,
    error_code: str,
) -> None:
    client = document_context.client
    _, token = create_user_and_token(client, "validator")
    workspace_id = create_workspace(client, token, "validation")

    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/documents",
        headers=auth_headers(token),
        files={"file": (filename, content, content_type)},
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code
    assert document_context.storage.objects == {}


@pytest.mark.integration
def test_document_access_is_tenant_scoped(
    document_context: DocumentTestContext,
) -> None:
    client = document_context.client
    _, tenant_a_token = create_user_and_token(client, "tenant-a-docs")
    _, tenant_b_token = create_user_and_token(client, "tenant-b-docs")
    tenant_a_workspace = create_workspace(client, tenant_a_token, "tenant-a-docs")
    tenant_b_workspace = create_workspace(client, tenant_b_token, "tenant-b-docs")
    uploaded = upload_markdown(client, tenant_b_token, tenant_b_workspace)
    assert uploaded.status_code == 202
    document_id = uploaded.json()["id"]

    list_attempt = client.get(
        f"/api/v1/workspaces/{tenant_b_workspace}/documents",
        headers=auth_headers(tenant_a_token),
    )
    get_attempt = client.get(
        f"/api/v1/documents/{document_id}",
        headers=auth_headers(tenant_a_token),
    )
    delete_attempt = client.delete(
        f"/api/v1/documents/{document_id}",
        headers=auth_headers(tenant_a_token),
    )
    assert list_attempt.status_code == 404
    assert get_attempt.status_code == 404
    assert delete_attempt.status_code == 404

    own_list = client.get(
        f"/api/v1/workspaces/{tenant_a_workspace}/documents",
        headers=auth_headers(tenant_a_token),
    )
    assert own_list.status_code == 200
    assert own_list.json() == []


@pytest.mark.integration
def test_uploader_can_delete_document_and_metadata(
    document_context: DocumentTestContext,
) -> None:
    client = document_context.client
    _, token = create_user_and_token(client, "deleter")
    workspace_id = create_workspace(client, token, "delete")
    uploaded = upload_markdown(client, token, workspace_id)
    assert uploaded.status_code == 202
    document = uploaded.json()

    response = client.delete(
        f"/api/v1/documents/{document['id']}",
        headers=auth_headers(token),
    )

    assert response.status_code == 204
    assert document["storage_key"] in document_context.storage.deleted_keys
    assert document["storage_key"] not in document_context.storage.objects
    get_response = client.get(
        f"/api/v1/documents/{document['id']}",
        headers=auth_headers(token),
    )
    assert get_response.status_code == 404


def test_upload_requires_authentication() -> None:
    settings = Settings(environment="test", _env_file=None)
    with TestClient(
        create_app(
            settings,
            object_storage=InMemoryObjectStorage(),
            ingestion_queue=InMemoryIngestionQueue(),
            vector_store=InMemoryVectorStore(),
        )
    ) as client:
        response = client.post(
            f"/api/v1/workspaces/{uuid4()}/documents",
            files={"file": ("notes.txt", b"notes", "text/plain")},
        )

    assert response.status_code == 401
