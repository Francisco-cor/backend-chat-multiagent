"""Minimal Python SDK for Backend Chat API — typed, httpx-based.

Covers:
 - auth.login / register
 - chat.create / stream / orchestrate
 - conversations list/get
 - api_keys lifecycle
 - billing usage
Works with both JWT (Authorization: Bearer) and API keys (X-API-Key / Bearer sk_).
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Iterator, Optional

import httpx


class _ChatNamespace:
    def __init__(self, client: "Client"):
        self._c = client

    def create(
        self,
        session_id: str,
        prompt: str,
        model: Optional[str] = None,
        use_search: bool = False,
        image_base64: Optional[str] = None,
        image_mime_type: Optional[str] = None,
        file_base64: Optional[str] = None,
        file_mime_type: Optional[str] = None,
    ) -> Any:
        payload: dict[str, Any] = {"session_id": session_id, "prompt": prompt, "use_search": use_search}
        if model:
            payload["model"] = model
        if image_base64:
            payload["image_base64"] = image_base64
            payload["image_mime_type"] = image_mime_type
        if file_base64:
            payload["file_base64"] = file_base64
            payload["file_mime_type"] = file_mime_type
        resp = self._c._request("POST", "/api/v1/chat/", json=payload)
        resp.raise_for_status()
        return resp.json()

    def stream(
        self,
        session_id: str,
        prompt: str,
        model: Optional[str] = None,
        use_search: bool = False,
    ) -> Iterator[str]:
        """Yield delta chunks (SSE)."""
        payload: dict[str, Any] = {"session_id": session_id, "prompt": prompt, "use_search": use_search}
        if model:
            payload["model"] = model
        with self._c._client.stream("POST", self._c._url("/api/v1/chat/stream"), json=payload, headers=self._c._headers()) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        if "delta" in obj:
                            yield obj["delta"]
                        elif "error" in obj:
                            raise RuntimeError(obj["error"])
                    except json.JSONDecodeError:
                        continue

    def orchestrate(self, session_id: str, prompt: str, model: Optional[str] = None, strategy: str = "auto") -> Any:
        payload = {"session_id": session_id, "prompt": prompt, "strategy": strategy}
        if model:
            payload["model"] = model
        resp = self._c._request("POST", "/api/v1/chat/orchestrate", json=payload)
        resp.raise_for_status()
        return resp.json()


class _ConversationsNamespace:
    def __init__(self, client: "Client"):
        self._c = client

    def list(self, limit: int = 20, cursor: Optional[int] = None) -> Any:
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        resp = self._c._request("GET", "/api/v1/conversations", params=params)
        resp.raise_for_status()
        return resp.json()

    def get_messages(self, conversation_id: int, limit: int = 50, cursor: Optional[int] = None) -> Any:
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        resp = self._c._request("GET", f"/api/v1/conversations/{conversation_id}/messages", params=params)
        resp.raise_for_status()
        return resp.json()


class _ApiKeysNamespace:
    def __init__(self, client: "Client"):
        self._c = client

    def create(self, name: str, scopes: Optional[list[str]] = None, expires_in_days: Optional[int] = None) -> Any:
        payload: dict[str, Any] = {"name": name}
        if scopes is not None:
            payload["scopes"] = scopes
        if expires_in_days is not None:
            payload["expires_in_days"] = expires_in_days
        resp = self._c._request("POST", "/api/v1/api-keys", json=payload)
        resp.raise_for_status()
        return resp.json()

    def list(self) -> Any:
        resp = self._c._request("GET", "/api/v1/api-keys")
        resp.raise_for_status()
        return resp.json()

    def delete(self, key_id: int) -> Any:
        resp = self._c._request("DELETE", f"/api/v1/api-keys/{key_id}")
        resp.raise_for_status()
        return resp.json()


class Client:
    """Sync client.

    Example:
        from backend_chat_sdk import Client
        client = Client(base_url="http://localhost:8005", token="...")
        client.chat.create(session_id="s1", prompt="hi")
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8005",
        token: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        headers: Optional[dict[str, str]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token or api_key  # alias
        self.api_key = api_key or (token if token and token.startswith("sk_") else None)
        self.timeout = timeout
        self._extra_headers = headers or {}
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)
        self.chat = _ChatNamespace(self)
        self.conversations = _ConversationsNamespace(self)
        self.api_keys = _ApiKeysNamespace(self)

    def _headers(self) -> dict[str, str]:
        h = dict(self._extra_headers)
        if self.token:
            if self.token.startswith("sk_"):
                # Supports both Bearer and X-API-Key; send both for compat
                h["Authorization"] = f"Bearer {self.token}"
                h["X-API-Key"] = self.token
            else:
                h["Authorization"] = f"Bearer {self.token}"
        return h

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        # inject auth headers
        headers = kwargs.pop("headers", {})
        merged = {**self._headers(), **headers}
        return self._client.request(method, path, headers=merged, **kwargs)

    def login(self, email: str, password: str) -> dict[str, Any]:
        resp = self._client.post("/api/v1/auth/login", data={"username": email, "password": password})
        resp.raise_for_status()
        data = resp.json()
        # auto-store token
        self.token = data.get("access_token")
        return data

    def register(self, email: str, password: str) -> dict[str, Any]:
        resp = self._client.post("/api/v1/auth/register", json={"email": email, "password": password})
        resp.raise_for_status()
        return resp.json()

    def health(self) -> dict[str, Any]:
        resp = self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# Aliases for compat
BackendChatClient = Client


class AsyncClient:
    """Async variant (httpx.AsyncClient)."""

    def __init__(self, base_url: str = "http://localhost:8005", token: Optional[str] = None, api_key: Optional[str] = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.token = token or api_key
        self.timeout = timeout
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.token:
            if self.token.startswith("sk_"):
                h["Authorization"] = f"Bearer {self.token}"
                h["X-API-Key"] = self.token
            else:
                h["Authorization"] = f"Bearer {self.token}"
        return h

    async def chat_create(self, session_id: str, prompt: str, model: Optional[str] = None) -> Any:
        payload: dict[str, Any] = {"session_id": session_id, "prompt": prompt}
        if model:
            payload["model"] = model
        resp = await self._client.post("/api/v1/chat/", json=payload, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "AsyncClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
