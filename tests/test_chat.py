import base64
import secrets
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

from app.services.llm_providers import GoogleGeminiProvider, OpenAIProvider, ClaudeProvider


async def _register_and_login(client: AsyncClient):
    email = f"chat_{secrets.token_hex(4)}@example.com"
    pwd = "StrongPass123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})
    resp = await client.post("/api/v1/auth/login", data={"username": email, "password": pwd})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_chat_json_success(client: AsyncClient):
    headers = await _register_and_login(client)
    with patch.object(GoogleGeminiProvider, "generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = "Hello from mocked Gemini"
        resp = await client.post(
            "/api/v1/chat/",
            json={"session_id": "sess_json_1", "prompt": "Hello AI", "model": "gemini-3.1-pro"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["reply"] == "Hello from mocked Gemini"
        assert data["session_id"] == "sess_json_1"
        assert data["model_used"] == "gemini-3.1-pro"


@pytest.mark.asyncio
async def test_chat_unauthorized(client: AsyncClient):
    resp = await client.post(
        "/api/v1/chat/",
        json={"session_id": "sess1", "prompt": "Hello"},
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_chat_invalid_model(client: AsyncClient):
    headers = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/chat/",
        json={"session_id": "sess1", "prompt": "hi", "model": "not-a-model"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "not allowed" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_chat_invalid_base64(client: AsyncClient):
    headers = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/chat/",
        json={
            "session_id": "sess1",
            "prompt": "hi",
            "model": "gemini-3.1-pro",
            "image_base64": "!!!notbase64!!!",
            "image_mime_type": "image/png",
        },
        headers=headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_chat_upload_success(client: AsyncClient):
    headers = await _register_and_login(client)
    with patch.object(GoogleGeminiProvider, "generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = "Processed upload"
        files = {"file": ("test.txt", b"hello file content", "text/plain")}
        data = {"session_id": "sess_upload_1", "prompt": "summarize file", "model": "gemini-3.1-pro"}
        resp = await client.post("/api/v1/chat/upload", data=data, files=files, headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["reply"] == "Processed upload"


@pytest.mark.asyncio
async def test_chat_upload_too_large(client: AsyncClient):
    headers = await _register_and_login(client)
    # MAX_UPLOAD_SIZE_MB is 10, so 11MB should fail
    large_content = b"x" * (11 * 1024 * 1024)
    files = {"file": ("large.bin", large_content, "application/octet-stream")}
    data = {"session_id": "sess_large", "prompt": "hi", "model": "gemini-3.1-pro"}
    resp = await client.post("/api/v1/chat/upload", data=data, files=files, headers=headers)
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_chat_stream_success(client: AsyncClient):
    headers = await _register_and_login(client)

    async def mock_stream(*args, **kwargs):
        for chunk in ["Hello ", "world", "!"]:
            yield chunk

    with patch.object(GoogleGeminiProvider, "generate_stream", side_effect=mock_stream):
        resp = await client.post(
            "/api/v1/chat/stream",
            json={"session_id": "sess_stream_1", "prompt": "hi", "model": "gemini-3.1-pro"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = resp.text
        assert "data: {\"delta\": \"Hello \"}" in body
        assert "data: [DONE]" in body


@pytest.mark.asyncio
async def test_chat_history_isolation(client: AsyncClient):
    """Two users same session_id should not share history (user_id filter)."""
    headers1 = await _register_and_login(client)
    headers2 = await _register_and_login(client)

    with patch.object(GoogleGeminiProvider, "generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = "reply1"
        resp1 = await client.post(
            "/api/v1/chat/",
            json={"session_id": "shared_session", "prompt": "user1 hello", "model": "gemini-3.1-pro"},
            headers=headers1,
        )
        assert resp1.status_code == 200

        mock_gen.return_value = "reply2"
        resp2 = await client.post(
            "/api/v1/chat/",
            json={"session_id": "shared_session", "prompt": "user2 hello", "model": "gemini-3.1-pro"},
            headers=headers2,
        )
        assert resp2.status_code == 200

    # Verify isolation by checking DB directly via chat history query
    # If isolation failed, second user would have history length 2 (user1 + user2), but should be 1
    # We test via second chat's provider receiving only its own history: mock and inspect call args
    with patch.object(GoogleGeminiProvider, "generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = "reply3"
        await client.post(
            "/api/v1/chat/",
            json={"session_id": "shared_session", "prompt": "user2 second", "model": "gemini-3.1-pro"},
            headers=headers2,
        )
        # history should contain only user2's prior messages (1 prior exchange = 2 messages, but limit 15)
        # The mock was called with history param
        call_kwargs = mock_gen.call_args.kwargs
        history = call_kwargs.get("history", [])
        # For user2, history should have 2 messages (user2 hello + reply2), not user1's
        assert len(history) == 2
        assert all("user2 hello" in m.content or "reply2" in m.content for m in history)


@pytest.mark.asyncio
async def test_chat_multimodal_image_base64(client: AsyncClient):
    headers = await _register_and_login(client)
    img_b64 = base64.b64encode(b"fake_image_data").decode()
    with patch.object(GoogleGeminiProvider, "generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = "image processed"
        resp = await client.post(
            "/api/v1/chat/",
            json={
                "session_id": "sess_img",
                "prompt": "describe",
                "model": "gemini-3.1-pro",
                "image_base64": img_b64,
                "image_mime_type": "image/png",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["reply"] == "image processed"
