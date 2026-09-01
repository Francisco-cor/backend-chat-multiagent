import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_metrics_endpoint(client: AsyncClient):
    # Make some requests to generate metrics
    await client.get("/")
    await client.get("/health")
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body


@pytest.mark.asyncio
async def test_metrics_latency_recorded(client: AsyncClient):
    await client.get("/")
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    # Should contain histogram buckets
    assert "http_request_duration_seconds_bucket" in resp.text
