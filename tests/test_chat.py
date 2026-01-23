import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch
from app.services.llm_providers import GoogleGeminiProvider

@pytest.mark.asyncio
async def test_chat_endpoint(client: AsyncClient):
    # Register/Login
    await client.post(
        "/api/v1/auth/register",
        json={"email": "chat@example.com", "password": "password123"}
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "chat@example.com", "password": "password123"}
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Mock LLM
    with patch.object(GoogleGeminiProvider, "generate", new_callable=AsyncMock) as mock_generate:
        mock_generate.return_value = "Hello from mocked Gemini"

        response = await client.post(
            "/api/v1/chat/",
            json={
                "session_id": "session1",
                "prompt": "Hello AI",
                "model": "gemini-2.5-pro"
            },
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["reply"] == "Hello from mocked Gemini"
        assert data["session_id"] == "session1"

@pytest.mark.asyncio
async def test_chat_unauthorized(client: AsyncClient):
    response = await client.post(
        "/api/v1/chat/",
        json={
            "session_id": "session1",
            "prompt": "Hello AI"
        }
    )
    assert response.status_code == 401
