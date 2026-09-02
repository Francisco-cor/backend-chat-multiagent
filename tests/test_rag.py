import secrets
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

from app.services.llm_providers import GoogleGeminiProvider, OpenAIProvider


async def _headers(client: AsyncClient):
    email = f"rag_{secrets.token_hex(4)}@example.com"
    pwd = "StrongPass123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pwd})
    r = await client.post("/api/v1/auth/login", data={"username": email, "password": pwd})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_ingest_text_and_search(client: AsyncClient):
    headers = await _headers(client)
    # Ingest
    r = await client.post(
        "/api/v1/documents/ingest-text",
        data={"title": "Doc1", "content": "The secret recipe is 42. Vault password banana.", "source": "test"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["document"]["title"] == "Doc1"
    assert data["chunks"] == 1

    # Search
    r = await client.get("/api/v1/documents/search?q=secret recipe", headers=headers)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["query"] == "secret recipe"
    assert len(j["results"]) >= 1
    assert "42" in j["results"][0]["content"]
    assert j["citations"][0]["content"] is not None


@pytest.mark.asyncio
async def test_upload_and_list(client: AsyncClient):
    headers = await _headers(client)
    file_content = b"Hello world about AI transformers. Important info about attention mechanism."
    r = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("test.txt", file_content, "text/plain")},
        data={"title": "FileDoc"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["document"]["title"] == "FileDoc"

    # List
    r = await client.get("/api/v1/documents", headers=headers)
    assert r.status_code == 200
    assert any(d["title"] == "FileDoc" for d in r.json())

    # Get single
    doc_id = r.json()[0]["id"]
    r = await client.get(f"/api/v1/documents/{doc_id}", headers=headers)
    assert r.status_code == 200

    # Delete
    r = await client.delete(f"/api/v1/documents/{doc_id}", headers=headers)
    assert r.status_code == 200
    r = await client.get(f"/api/v1/documents/{doc_id}", headers=headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_rag_isolation(client: AsyncClient):
    h1 = await _headers(client)
    h2 = await _headers(client)
    # User1 ingest
    await client.post(
        "/api/v1/documents/ingest-text",
        data={"title": "Private", "content": "User1 secret is apple", "source": "s"},
        headers=h1,
    )
    # User2 search should not find User1's doc
    r = await client.get("/api/v1/documents/search?q=apple", headers=h2)
    assert r.status_code == 200
    assert len(r.json()["results"]) == 0
    # User1 should find it
    r = await client.get("/api/v1/documents/search?q=apple", headers=h1)
    assert len(r.json()["results"]) == 1


@pytest.mark.asyncio
async def test_chunking_and_embedding(client: AsyncClient):
    headers = await _headers(client)
    long_text = " ".join([f"sentence {i} about AI." for i in range(100)])  # ~2000 chars
    r = await client.post(
        "/api/v1/documents/ingest-text",
        data={"title": "Long", "content": long_text, "source": "s"},
        headers=headers,
    )
    assert r.status_code == 200
    # Should have multiple chunks (512 size)
    assert r.json()["chunks"] > 1
    # Search for sentence 50
    r = await client.get("/api/v1/documents/search?q=sentence 50", headers=headers)
    assert r.status_code == 200
    assert len(r.json()["results"]) >= 1


@pytest.mark.asyncio
async def test_orchestrator_uses_rag_citations(client: AsyncClient):
    headers = await _headers(client)
    await client.post(
        "/api/v1/documents/ingest-text",
        data={"title": "RAGDoc", "content": "The vault code is 999. Keep it secret.", "source": "s"},
        headers=headers,
    )

    # Mock researcher to verify it receives RAG context
    with patch.object(GoogleGeminiProvider, "generate", new_callable=AsyncMock) as mk_gem, patch.object(
        OpenAIProvider, "generate", new_callable=AsyncMock
    ) as mk_oai:
        async def gem_side_effect(prompt, history, **kwargs):
            if "vault" in prompt.lower():
                return "The vault code is 999 [1]"
            return "generic"

        mk_gem.side_effect = gem_side_effect
        mk_oai.return_value = "analyst"

        r = await client.post(
            "/api/v1/chat/orchestrate",
            json={"session_id": "rag_sess", "prompt": "what is vault code?", "model": "gemini-3.1-pro", "strategy": "auto"},
            headers=headers,
        )
        assert r.status_code == 200
        data = r.json()
        # Should have used RAG and returned citation
        assert "999" in data["reply"]
        assert "[1]" in data["reply"]
        # Trace should have researcher with rag
        assert any(t["agent"] == "researcher" for t in data["trace"])


@pytest.mark.asyncio
async def test_retriever_direct():
    # Test embedding and retriever directly with dummy vectors
    from app.services.embedding_service import _dummy_vector
    from app.services.retriever import cosine_similarity

    v1 = _dummy_vector("hello world", dim=64)
    v2 = _dummy_vector("hello world", dim=64)
    v3 = _dummy_vector("completely different", dim=64)
    assert cosine_similarity(v1, v2) == pytest.approx(1.0, abs=0.01)
    assert cosine_similarity(v1, v3) < 0.99
