import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def auth_client() -> Iterator[TestClient]:
    database_url = os.getenv("EKH_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("EKH_TEST_DATABASE_URL is required for authentication tests")

    settings = Settings(
        environment="test",
        database_url=database_url,
        jwt_secret="test-only-jwt-secret-with-at-least-32-characters",
        _env_file=None,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def user_payload() -> dict[str, str]:
    return {
        "email": f"user-{uuid4().hex}@example.com",
        "password": "correct horse battery staple",
        "display_name": "Test Engineer",
    }


def register_and_login(client: TestClient) -> tuple[dict[str, str], dict[str, str]]:
    user = user_payload()
    assert client.post("/api/v1/auth/register", json=user).status_code == 201
    response = client.post(
        "/api/v1/auth/login",
        json={"email": user["email"], "password": user["password"]},
    )
    assert response.status_code == 200
    return user, response.json()


@pytest.mark.integration
def test_registration(auth_client: TestClient) -> None:
    user = user_payload()

    response = auth_client.post("/api/v1/auth/register", json=user)

    assert response.status_code == 201
    assert response.json()["email"] == user["email"]
    assert response.json()["display_name"] == user["display_name"]
    assert response.json()["is_active"] is True
    assert "password" not in response.json()
    assert "hashed_password" not in response.json()


@pytest.mark.integration
def test_duplicate_email_is_rejected(auth_client: TestClient) -> None:
    user = user_payload()
    assert auth_client.post("/api/v1/auth/register", json=user).status_code == 201

    response = auth_client.post("/api/v1/auth/register", json=user)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_already_registered"


@pytest.mark.integration
def test_valid_login_returns_tokens(auth_client: TestClient) -> None:
    _, tokens = register_and_login(auth_client)

    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert tokens["access_token"] != tokens["refresh_token"]


@pytest.mark.integration
def test_invalid_login_uses_generic_response(auth_client: TestClient) -> None:
    user = user_payload()
    assert auth_client.post("/api/v1/auth/register", json=user).status_code == 201

    wrong_password_response = auth_client.post(
        "/api/v1/auth/login",
        json={"email": user["email"], "password": "wrong password"},
    )
    unknown_user_response = auth_client.post(
        "/api/v1/auth/login",
        json={"email": f"missing-{uuid4().hex}@example.com", "password": "wrong"},
    )

    expected_response = {
        "error": {
            "code": "invalid_credentials",
            "message": "Invalid email or password",
        }
    }
    assert wrong_password_response.status_code == 401
    assert wrong_password_response.json() == expected_response
    assert unknown_user_response.status_code == 401
    assert unknown_user_response.json() == expected_response


def test_protected_endpoint_requires_token() -> None:
    settings = Settings(environment="test", _env_file=None)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/users/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.integration
def test_protected_endpoint_returns_current_user(auth_client: TestClient) -> None:
    user, tokens = register_and_login(auth_client)

    response = auth_client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == user["email"]


@pytest.mark.integration
def test_refresh_returns_a_new_usable_token_pair(auth_client: TestClient) -> None:
    user, tokens = register_and_login(auth_client)

    access_token_response = auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["access_token"]},
    )
    assert access_token_response.status_code == 401

    refresh_response = auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )

    assert refresh_response.status_code == 200
    refreshed_tokens = refresh_response.json()
    assert refreshed_tokens["access_token"] != tokens["access_token"]
    assert refreshed_tokens["refresh_token"] != tokens["refresh_token"]

    me_response = auth_client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {refreshed_tokens['access_token']}"},
    )
    assert me_response.status_code == 200
    assert me_response.json()["email"] == user["email"]
