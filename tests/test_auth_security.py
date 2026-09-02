import secrets
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

from app.services.llm_providers import GoogleGeminiProvider


@pytest.mark.asyncio
async def test_register_weak_password_rejected(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": f"weak_{secrets.token_hex(4)}@example.com", "password": "weak"},
    )
    assert resp.status_code == 422
    assert "at least 12" in resp.text


@pytest.mark.asyncio
async def test_register_common_password_rejected(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": f"common_{secrets.token_hex(4)}@example.com", "password": "Password123!"},
    )
    # Password123! is not in blocklist? our blocklist has password123 lower, but Password123! has ! so not exact match
    # Try exactly common
    resp2 = await client.post(
        "/api/v1/auth/register",
        json={"email": f"common2_{secrets.token_hex(4)}@example.com", "password": "password"},
    )
    assert resp2.status_code == 422


@pytest.mark.asyncio
async def test_login_lockout(client: AsyncClient):
    email = f"lock_{secrets.token_hex(4)}@example.com"
    pwd = "StrongPass123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})
    # 5 wrong attempts
    for _ in range(5):
        r = await client.post("/api/v1/auth/login", data={"username": email, "password": "WrongPass123!"})
        assert r.status_code == 400
    # 6th should be locked even with correct password
    r = await client.post("/api/v1/auth/login", data={"username": email, "password": pwd})
    assert r.status_code == 423
    assert "locked" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_refresh_flow(client: AsyncClient):
    email = f"ref_{secrets.token_hex(4)}@example.com"
    pwd = "StrongPass123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})
    r = await client.post("/api/v1/auth/login", data={"username": email, "password": pwd})
    assert r.status_code == 200
    data = r.json()
    assert "refresh_token" in data
    assert "expires_in" in data
    refresh = data["refresh_token"]
    access = data["access_token"]

    # refresh success
    r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 200
    assert "access_token" in r2.json()
    assert "refresh_token" in r2.json()
    new_refresh = r2.json()["refresh_token"]
    new_access = r2.json()["access_token"]
    assert new_refresh != refresh
    assert new_access != access

    # old refresh revoked
    r3 = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r3.status_code == 401
    assert "revoked" in r3.text.lower()

    # new refresh still works once
    r4 = await client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert r4.status_code == 200


@pytest.mark.asyncio
async def test_logout_revokes_access(client: AsyncClient):
    email = f"logout_{secrets.token_hex(4)}@example.com"
    pwd = "StrongPass123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})
    r = await client.post("/api/v1/auth/login", data={"username": email, "password": pwd})
    access = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {access}"}
    # should work before logout
    with patch.object(GoogleGeminiProvider, "generate", new_callable=AsyncMock) as mk:
        mk.return_value = "ok"
        ok = await client.post(
            "/api/v1/chat/",
            json={"session_id": "s", "prompt": "hi", "model": "gemini-3.1-pro"},
            headers=headers,
        )
        assert ok.status_code == 200

    # logout
    lo = await client.post("/api/v1/auth/logout", headers=headers)
    assert lo.status_code == 200

    # should be revoked now
    with patch.object(GoogleGeminiProvider, "generate", new_callable=AsyncMock) as mk:
        mk.return_value = "ok"
        bad = await client.post(
            "/api/v1/chat/",
            json={"session_id": "s", "prompt": "hi", "model": "gemini-3.1-pro"},
            headers=headers,
        )
        assert bad.status_code == 401
        assert "revoked" in bad.text.lower()


@pytest.mark.asyncio
async def test_security_headers_present(client: AsyncClient):
    r = await client.get("/")
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert "content-security-policy" in r.headers
    assert "referrer-policy" in r.headers


@pytest.mark.asyncio
async def test_refresh_with_access_token_fails(client: AsyncClient):
    email = f"badtype_{secrets.token_hex(4)}@example.com"
    pwd = "StrongPass123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})
    r = await client.post("/api/v1/auth/login", data={"username": email, "password": pwd})
    access = r.json()["access_token"]
    # try to use access as refresh
    r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": access})
    assert r2.status_code == 401
