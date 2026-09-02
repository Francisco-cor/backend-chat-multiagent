import secrets
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch
from sqlalchemy import select

from app.services.llm_providers import GoogleGeminiProvider


async def _register_and_login(client: AsyncClient):
    email = f"f11_{secrets.token_hex(4)}@example.com"
    pwd = "StrongPass123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})
    resp = await client.post("/api/v1/auth/login", data={"username": email, "password": pwd})
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    return headers, token, email


@pytest.mark.asyncio
async def test_cache_embedding_and_llm(client: AsyncClient):
    # Test cache service directly
    from app.services.cache_service import cache_service
    await cache_service.clear()
    # embedding cache
    await cache_service.set_embedding("hello world", "dummy", "test-model", [0.1, 0.2, 0.3])
    vec = await cache_service.get_embedding("hello world", "dummy", "test-model")
    assert vec == [0.1, 0.2, 0.3]
    # LLM cache
    await cache_service.set_llm("prompt1", "gemini-3.1-pro", "cached reply", "hh", "th")
    out = await cache_service.get_llm("prompt1", "gemini-3.1-pro", "hh", "th")
    assert out == "cached reply"
    # miss
    out = await cache_service.get_llm("other", "gemini-3.1-pro", "hh", "th")
    assert out is None


@pytest.mark.asyncio
async def test_llm_cache_integration(client: AsyncClient):
    headers, _, _ = await _register_and_login(client)
    from app.services.cache_service import cache_service
    await cache_service.clear()
    # Test cache via direct provider (no outer patch needed)
    from app.core.config import settings
    provider = GoogleGeminiProvider(model_name="gemini-3.1-pro", api_key="test")
    # Mock the internal client to return deterministic
    with patch.object(provider.client.models, "generate_content") as mock_gem:
        mock_gem.return_value = type("R", (), {"text": "hello cached", "function_calls": None, "candidates": []})()
        out1 = await provider.generate(prompt="test cache prompt", history=[])
        assert out1 == "hello cached"
        # second call should hit cache and not call generate_content again
        mock_gem.reset_mock()
        out2 = await provider.generate(prompt="test cache prompt", history=[])
        assert out2 == "hello cached"
        # generate_content should not have been called second time due to cache
        mock_gem.assert_not_called()


@pytest.mark.asyncio
async def test_tenant_org_flow(client: AsyncClient, db):
    headers, _, email = await _register_and_login(client)
    # create org
    resp = await client.post("/api/v1/organizations", json={"name": "TestOrg"}, headers=headers)
    assert resp.status_code == 200, resp.text
    org_id = resp.json()["id"]
    # list
    resp = await client.get("/api/v1/organizations", headers=headers)
    assert resp.status_code == 200
    assert any(o["id"] == org_id for o in resp.json())
    # get org
    resp = await client.get(f"/api/v1/organizations/{org_id}", headers=headers)
    assert resp.status_code == 200
    # invite non-existing user (returns token)
    resp = await client.post(f"/api/v1/organizations/{org_id}/invite", json={"email": "invited@example.com", "role": "member"}, headers=headers)
    assert resp.status_code == 200
    assert "invite_token" in resp.json()
    # create second user and accept invite
    headers2, _, _ = await _register_and_login(client)
    resp = await client.post(f"/api/v1/organizations/{org_id}/accept", json={"invite_token": "any"}, headers=headers2)
    assert resp.status_code == 200, resp.text
    # list members should have 2
    resp = await client.get(f"/api/v1/organizations/{org_id}/members", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 2
    # X-Org-Id header should work for chat (org isolation)
    with patch.object(GoogleGeminiProvider, "generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = "org chat"
        resp = await client.post(
            "/api/v1/chat/",
            json={"session_id": "sess_org", "prompt": "hello org", "model": "gemini-3.1-pro"},
            headers={**headers, "X-Org-Id": str(org_id)},
        )
        assert resp.status_code == 200
    # non-member should be rejected
    headers3, _, _ = await _register_and_login(client)
    resp = await client.get(f"/api/v1/organizations/{org_id}", headers=headers3)
    assert resp.status_code == 403
    # isolation: third user not in org cannot use X-Org-Id
    with patch.object(GoogleGeminiProvider, "generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = "should not"
        resp = await client.post(
            "/api/v1/chat/",
            json={"session_id": "sess_org2", "prompt": "hi", "model": "gemini-3.1-pro"},
            headers={**headers3, "X-Org-Id": str(org_id)},
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_compliance_export_and_delete(client: AsyncClient):
    headers, _, email = await _register_and_login(client)
    # create some data via chat
    with patch.object(GoogleGeminiProvider, "generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = "compliance data"
        await client.post(
            "/api/v1/chat/",
            json={"session_id": "sess_comp", "prompt": "hello", "model": "gemini-3.1-pro"},
            headers=headers,
        )
    # export
    resp = await client.get("/api/v1/compliance/export", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "conversations" in data
    assert "messages" in data
    assert data["user"]["email"] == email
    # audit
    resp = await client.get("/api/v1/compliance/audit?limit=10", headers=headers)
    assert resp.status_code == 200
    assert any(a["action"] == "gdpr.export" for a in resp.json())
    # delete with wrong confirm should 400
    resp = await client.request("DELETE", "/api/v1/compliance/account", json={"confirm": "NO"}, headers=headers)
    assert resp.status_code == 400
    # delete correctly
    resp = await client.request("DELETE", "/api/v1/compliance/account", json={"confirm": "DELETE"}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert "deleted" in resp.json()["detail"].lower()
    # after delete, chat should fail due to inactive
    with patch.object(GoogleGeminiProvider, "generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = "should not"
        resp = await client.post(
            "/api/v1/chat/",
            json={"session_id": "sess_after", "prompt": "hi", "model": "gemini-3.1-pro"},
            headers=headers,
        )
        assert resp.status_code in (400, 401)


@pytest.mark.asyncio
async def test_worker_queue_enqueue():
    from app.worker.queue import enqueue, get_job
    job_id = await enqueue("ingest_document", {"document_id": 1, "user_id": 1})
    assert job_id
    job = await get_job(job_id)
    assert job is not None
    assert job["task"] == "ingest_document"
    # run dispatch directly
    from app.worker.tasks import dispatch
    result = await dispatch("ingest_document", {"document_id": 1, "user_id": 1})
    assert result["status"] == "ingested"
    # webhook stub
    result = await dispatch("webhook", {"url": "http://example.com/hook", "event": "test", "data": {"x": 1}})
    assert "status" in result


@pytest.mark.asyncio
async def test_tracing_setup():
    from app.core.tracing import setup_tracing, get_tracer
    tracer = setup_tracing(service_name="test")
    # should be None when disabled (default) or tracer when enabled
    # just ensure no exception
    t = get_tracer("test")
    assert t is not None
    # test span context
    with t.start_as_current_span("test-span") as span:
        span.set_attribute("test", "value")


@pytest.mark.asyncio
async def test_eval_runner():
    # Test eval runner directly (mock)
    import os
    os.environ["EVAL_MOCK"] = "1"
    from evals.runner import run_case
    case = {"id": "eval_test", "prompt": "Hello world", "expected_keywords": ["Hello"], "category": "general"}
    result = await run_case(case, use_mock=True)
    assert result["passed"] is True
    assert result["score"] >= 0.6
