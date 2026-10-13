from collections.abc import Iterator
import os
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def tenant_client() -> Iterator[TestClient]:
    database_url = os.getenv("EKH_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("EKH_TEST_DATABASE_URL is required for tenancy tests")

    settings = Settings(
        environment="test",
        database_url=database_url,
        jwt_secret="test-only-jwt-secret-with-at-least-32-characters",
        _env_file=None,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def create_user_and_token(
    client: TestClient,
    label: str,
) -> tuple[dict[str, str], str]:
    user = {
        "email": f"{label}-{uuid4().hex}@example.com",
        "password": "correct horse battery staple",
        "display_name": label.title(),
    }
    assert client.post("/api/v1/auth/register", json=user).status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": user["email"], "password": user["password"]},
    )
    assert login.status_code == 200
    return user, login.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_organization_for(
    client: TestClient,
    token: str,
    label: str,
) -> dict[str, str]:
    response = client.post(
        "/api/v1/organizations",
        headers=auth_headers(token),
        json={
            "name": f"{label.title()} Organization",
            "slug": f"{label}-{uuid4().hex}",
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.integration
def test_create_and_list_my_organizations(tenant_client: TestClient) -> None:
    _, token = create_user_and_token(tenant_client, "owner")
    organization = create_organization_for(tenant_client, token, "engineering")

    response = tenant_client.get(
        "/api/v1/organizations",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert organization["id"] in {item["id"] for item in response.json()}


@pytest.mark.integration
def test_roles_control_workspace_management(tenant_client: TestClient) -> None:
    owner, owner_token = create_user_and_token(tenant_client, "owner")
    member, member_token = create_user_and_token(tenant_client, "member")
    admin, admin_token = create_user_and_token(tenant_client, "admin")
    organization = create_organization_for(tenant_client, owner_token, "platform")
    organization_id = organization["id"]

    member_response = tenant_client.post(
        f"/api/v1/organizations/{organization_id}/members",
        headers=auth_headers(owner_token),
        json={"email": member["email"], "role": "member"},
    )
    admin_response = tenant_client.post(
        f"/api/v1/organizations/{organization_id}/members",
        headers=auth_headers(owner_token),
        json={"email": admin["email"], "role": "admin"},
    )
    assert member_response.status_code == 201
    assert admin_response.status_code == 201

    member_create = tenant_client.post(
        f"/api/v1/organizations/{organization_id}/workspaces",
        headers=auth_headers(member_token),
        json={"name": "Member Workspace"},
    )
    assert member_create.status_code == 403

    admin_create = tenant_client.post(
        f"/api/v1/organizations/{organization_id}/workspaces",
        headers=auth_headers(admin_token),
        json={"name": "Platform Docs", "description": "Shared documentation"},
    )
    assert admin_create.status_code == 201

    member_list = tenant_client.get(
        f"/api/v1/organizations/{organization_id}/workspaces",
        headers=auth_headers(member_token),
    )
    assert member_list.status_code == 200
    assert [item["name"] for item in member_list.json()] == ["Platform Docs"]


@pytest.mark.integration
def test_user_cannot_access_another_tenants_workspaces(
    tenant_client: TestClient,
) -> None:
    _, tenant_a_token = create_user_and_token(tenant_client, "tenant-a")
    _, tenant_b_token = create_user_and_token(tenant_client, "tenant-b")
    tenant_a = create_organization_for(tenant_client, tenant_a_token, "tenant-a")
    tenant_b = create_organization_for(tenant_client, tenant_b_token, "tenant-b")

    workspace = tenant_client.post(
        f"/api/v1/organizations/{tenant_b['id']}/workspaces",
        headers=auth_headers(tenant_b_token),
        json={"name": "Private Workspace", "description": "Tenant B only"},
    )
    assert workspace.status_code == 201

    list_attempt = tenant_client.get(
        f"/api/v1/organizations/{tenant_b['id']}/workspaces",
        headers=auth_headers(tenant_a_token),
    )
    create_attempt = tenant_client.post(
        f"/api/v1/organizations/{tenant_b['id']}/workspaces",
        headers=auth_headers(tenant_a_token),
        json={"name": "Intrusion"},
    )
    add_member_attempt = tenant_client.post(
        f"/api/v1/organizations/{tenant_b['id']}/members",
        headers=auth_headers(tenant_a_token),
        json={"email": "nobody@example.com", "role": "member"},
    )

    assert list_attempt.status_code == 404
    assert create_attempt.status_code == 404
    assert add_member_attempt.status_code == 404

    tenant_a_list = tenant_client.get(
        f"/api/v1/organizations/{tenant_a['id']}/workspaces",
        headers=auth_headers(tenant_a_token),
    )
    assert tenant_a_list.status_code == 200
    assert tenant_a_list.json() == []
