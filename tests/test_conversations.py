import secrets
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

from app.services.llm_providers import GoogleGeminiProvider


async def _register_headers(client: AsyncClient):
    email = f"conv_{secrets.token_hex(4)}@example.com"
    pwd = "StrongPass123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})
    r = await client.post("/api/v1/auth/login", data={"username": email, "password": pwd})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, email


@pytest.mark.asyncio
async def test_conversations_crud_and_pagination(client: AsyncClient):
    headers, _ = await _register_headers(client)

    # Create 3 conversations via chat with different session_ids
    for sess in ["sessA", "sessB", "sessC"]:
        with patch.object(GoogleGeminiProvider, "generate", new_callable=AsyncMock) as mk:
            mk.return_value = f"reply {sess}"
            r = await client.post(
                "/api/v1/chat/",
                json={"session_id": sess, "prompt": f"hello {sess}", "model": "gemini-3.1-pro"},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            # Check usage present
            assert "usage" in r.json()
            assert r.json()["usage"]["total_tokens"] > 0

    # List with limit 2
    r = await client.get("/api/v1/conversations?limit=2", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 2
    assert data["has_more"] is True
    assert data["next_cursor"] is not None

    # Next page
    cursor = data["next_cursor"]
    r2 = await client.get(f"/api/v1/conversations?limit=2&cursor={cursor}", headers=headers)
    assert r2.status_code == 200
    data2 = r2.json()
    assert len(data2["items"]) == 1
    assert data2["has_more"] is False

    # Get single conversation
    conv_id = data["items"][0]["id"]
    r = await client.get(f"/api/v1/conversations/{conv_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == conv_id

    # Messages
    r = await client.get(f"/api/v1/conversations/{conv_id}/messages?limit=10", headers=headers)
    assert r.status_code == 200
    msgs = r.json()["items"]
    assert len(msgs) == 2  # user + model
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "model"
    assert msgs[0]["tokens"] is not None


@pytest.mark.asyncio
async def test_conversations_isolation(client: AsyncClient):
    headers1, _ = await _register_headers(client)
    headers2, _ = await _register_headers(client)

    # user1 creates
    with patch.object(GoogleGeminiProvider, "generate", new_callable=AsyncMock) as mk:
        mk.return_value = "hi"
        await client.post(
            "/api/v1/chat/", json={"session_id": "iso_sess", "prompt": "hello", "model": "gemini-3.1-pro"}, headers=headers1
        )

    # user2 list should be empty
    r = await client.get("/api/v1/conversations", headers=headers2)
    assert r.status_code == 200
    assert len(r.json()["items"]) == 0

    # user2 cannot get user1's conversation
    r1 = await client.get("/api/v1/conversations", headers=headers1)
    conv_id = r1.json()["items"][0]["id"]
    r2 = await client.get(f"/api/v1/conversations/{conv_id}", headers=headers2)
    assert r2.status_code == 404

    # user2 cannot get messages
    r3 = await client.get(f"/api/v1/conversations/{conv_id}/messages", headers=headers2)
    assert r3.status_code == 404


@pytest.mark.asyncio
async def test_conversations_patch_and_delete(client: AsyncClient):
    headers, _ = await _register_headers(client)

    with patch.object(GoogleGeminiProvider, "generate", new_callable=AsyncMock) as mk:
        mk.return_value = "reply"
        await client.post(
            "/api/v1/chat/", json={"session_id": "sess_patch", "prompt": "hello patch", "model": "gemini-3.1-pro"}, headers=headers
        )

    r = await client.get("/api/v1/conversations", headers=headers)
    conv_id = r.json()["items"][0]["id"]

    # Patch title
    r = await client.patch(f"/api/v1/conversations/{conv_id}", json={"title": "My New Title"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["title"] == "My New Title"

    # Soft delete
    r = await client.delete(f"/api/v1/conversations/{conv_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["hard"] is False

    # List should be empty after soft delete
    r = await client.get("/api/v1/conversations", headers=headers)
    assert len(r.json()["items"]) == 0

    # Get should 404 after soft delete
    r = await client.get(f"/api/v1/conversations/{conv_id}", headers=headers)
    assert r.status_code == 404

    # Restore
    r = await client.post(f"/api/v1/conversations/{conv_id}/restore", headers=headers)
    assert r.status_code == 200

    # List again should have 1
    r = await client.get("/api/v1/conversations", headers=headers)
    assert len(r.json()["items"]) == 1

    # Hard delete
    r = await client.delete(f"/api/v1/conversations/{conv_id}?hard=true", headers=headers)
    assert r.status_code == 200
    assert r.json()["hard"] is True

    # List empty after hard delete
    r = await client.get("/api/v1/conversations", headers=headers)
    assert len(r.json()["items"]) == 0

    # Restore should fail after hard delete
    r = await client.post(f"/api/v1/conversations/{conv_id}/restore", headers=headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_messages_pagination(client: AsyncClient):
    headers, _ = await _register_headers(client)

    # Create conversation with multiple exchanges (6 messages total = 3 exchanges)
    for i in range(3):
        with patch.object(GoogleGeminiProvider, "generate", new_callable=AsyncMock) as mk:
            mk.return_value = f"reply {i}"
            await client.post(
                "/api/v1/chat/", json={"session_id": "paginate_sess", "prompt": f"msg {i}", "model": "gemini-3.1-pro"}, headers=headers
            )

    r = await client.get("/api/v1/conversations", headers=headers)
    conv_id = r.json()["items"][0]["id"]

    # Get messages with limit 2 (should paginate)
    r = await client.get(f"/api/v1/conversations/{conv_id}/messages?limit=2", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 2
    assert data["has_more"] is True
    assert data["next_cursor"] is not None

    cursor = data["next_cursor"]
    r2 = await client.get(f"/api/v1/conversations/{conv_id}/messages?limit=2&cursor={cursor}", headers=headers)
    assert r2.status_code == 200
    data2 = r2.json()
    assert len(data2["items"]) == 2
    assert data2["has_more"] is True

    cursor2 = data2["next_cursor"]
    r3 = await client.get(f"/api/v1/conversations/{conv_id}/messages?limit=2&cursor={cursor2}", headers=headers)
    assert r3.status_code == 200
    data3 = r3.json()
    assert len(data3["items"]) == 2
    assert data3["has_more"] is False


@pytest.mark.asyncio
async def test_create_conversation_endpoint(client: AsyncClient):
    headers, _ = await _register_headers(client)
    r = await client.post(
        "/api/v1/conversations", json={"session_id": "new_sess", "title": "Explicit Title", "model": "gemini-3.1-pro"}, headers=headers
    )
    assert r.status_code == 201
    assert r.json()["title"] == "Explicit Title"
    assert r.json()["legacy_session_id"] == "new_sess"


@pytest.mark.asyncio
async def test_unauthorized_conversations(client: AsyncClient):
    r = await client.get("/api/v1/conversations")
    assert r.status_code in (401, 403)
