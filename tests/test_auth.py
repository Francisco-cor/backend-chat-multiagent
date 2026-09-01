import secrets
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    email = f"reg_{secrets.token_hex(4)}@example.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "StrongPass123!"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["email"] == email
    assert "id" in data
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_register_duplicate(client: AsyncClient):
    email = f"dup_{secrets.token_hex(4)}@example.com"
    payload = {"email": email, "password": "StrongPass123!"}
    r1 = await client.post("/api/v1/auth/register", json=payload)
    assert r1.status_code == 200
    r2 = await client.post("/api/v1/auth/register", json=payload)
    assert r2.status_code == 400
    assert "already exists" in r2.json()["detail"]


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    email = f"login_{secrets.token_hex(4)}@example.com"
    pwd = "StrongPass123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": pwd},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    email = f"wrongpwd_{secrets.token_hex(4)}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "StrongPass123!"})
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "WrongPass999"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Incorrect email or password"


@pytest.mark.asyncio
async def test_login_nonexistent_user_timing_safe(client: AsyncClient):
    # Should return same 400 as wrong password (timing-safe dummy hash)
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": f"nouser_{secrets.token_hex(4)}@example.com", "password": "whatever123"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Incorrect email or password"


@pytest.mark.asyncio
async def test_protected_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/api/v1/chat/",
        json={"session_id": "sess1", "prompt": "hello"},
    )
    # FastAPI OAuth2 returns 401 when no token
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_protected_invalid_token(client: AsyncClient):
    resp = await client.post(
        "/api/v1/chat/",
        json={"session_id": "sess1", "prompt": "hello"},
        headers={"Authorization": "Bearer invalid.token.here"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Could not validate credentials"


@pytest.mark.asyncio
async def test_register_invalid_email(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "pass123"},
    )
    assert resp.status_code == 422
