import asyncio
import base64
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, Mock

from app.db.models import ConversationHistory
from app.services.llm_providers import (
    GoogleGeminiProvider,
    OpenAIProvider,
    ClaudeProvider,
    SYSTEM_INSTRUCTION,
)
from app.core.config import settings


def _make_history():
    return [
        ConversationHistory(session_id="s", role="user", content="hi", user_id=1),
        ConversationHistory(session_id="s", role="model", content="hello", user_id=1),
    ]


@pytest.mark.asyncio
async def test_google_format_content():
    provider = GoogleGeminiProvider(model_name="gemini-3.1-pro", api_key="fake")
    history = _make_history()
    contents = provider._format_content(history)
    assert len(contents) == 2
    assert contents[0].role == "user"
    assert contents[1].role == "model"


@pytest.mark.asyncio
async def test_google_generate_success():
    provider = GoogleGeminiProvider(model_name="gemini-3.1-pro", api_key="fake")
    mock_response = MagicMock()
    mock_response.text = "mocked reply "

    with patch.object(provider.client.models, "generate_content", return_value=mock_response):
        reply = await provider.generate(prompt="test", history=[])
        assert reply == "mocked reply"


@pytest.mark.asyncio
async def test_google_generate_with_search_and_image():
    provider = GoogleGeminiProvider(model_name="gemini-3.1-pro", api_key="fake")
    mock_response = MagicMock()
    mock_response.text = "reply with search"

    img_b64 = base64.b64encode(b"fakeimg").decode()
    image_data = {"data": img_b64, "mime_type": "image/png"}

    with patch.object(provider.client.models, "generate_content", return_value=mock_response) as mock_call:
        reply = await provider.generate(prompt="describe", history=[], image_data=image_data, use_search=True)
        assert reply == "reply with search"
        # Verify generate_content called with correct config (search tool)
        call_kwargs = mock_call.call_args.kwargs
        assert call_kwargs["model"] == "gemini-3.1-pro"
        # config should contain tools with google_search
        assert call_kwargs["config"].tools is not None


@pytest.mark.asyncio
async def test_google_generate_timeout(monkeypatch):
    provider = GoogleGeminiProvider(model_name="gemini-3.1-pro", api_key="fake")

    def slow_call(*args, **kwargs):
        import time

        time.sleep(0.5)
        return MagicMock(text="late")

    monkeypatch.setattr(settings, "LLM_TIMEOUT_SECONDS", 0.05)
    with patch.object(provider.client.models, "generate_content", side_effect=slow_call):
        with pytest.raises(RuntimeError, match="timed out"):
            await provider.generate(prompt="hi", history=[])


@pytest.mark.asyncio
async def test_google_generate_stream():
    provider = GoogleGeminiProvider(model_name="gemini-3.1-pro", api_key="fake")

    async def _gen():
        for txt in ["hello ", "world"]:
            mock_chunk = MagicMock()
            mock_chunk.text = txt
            yield mock_chunk

    def fake_stream(*args, **kwargs):
        return _gen()

    provider.client.aio.models.generate_content_stream = fake_stream
    chunks = []
    async for c in provider.generate_stream(prompt="hi", history=[]):
        chunks.append(c)
    assert chunks == ["hello ", "world"]


@pytest.mark.asyncio
async def test_openai_provider_mapping_and_generate():
    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.output_text = "openai reply"
    mock_client.responses.create.return_value = mock_resp

    provider = OpenAIProvider(model_name="gpt-5.4-mini", client=mock_client)
    assert provider.effort == "low"
    assert provider.model_name == "gpt-5.4"

    reply = await provider.generate(prompt="hi", history=[])
    assert reply == "openai reply"
    mock_client.responses.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_openai_provider_image_and_file_handling():
    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.output_text = "reply"
    mock_client.responses.create.return_value = mock_resp

    provider = OpenAIProvider(model_name="gpt-5.4-medium", client=mock_client)
    assert provider.effort == "medium"

    img_b64 = base64.b64encode(b"img").decode()
    file_b64 = base64.b64encode(b"file content text").decode()
    image_data = {"data": img_b64, "mime_type": "image/png"}
    file_data = {"data": file_b64, "mime_type": "text/plain"}

    reply = await provider.generate(prompt="hi", history=[], image_data=image_data, file_data=file_data)
    assert reply == "reply"
    # Check that input contains image and file text
    call_input = mock_client.responses.create.call_args.kwargs["input"]
    # last message is user
    user_msg = call_input[-1]
    assert any(c.get("type") == "input_image" for c in user_msg["content"])


@pytest.mark.asyncio
async def test_openai_no_client_raises():
    provider = OpenAIProvider(model_name="gpt-5.4-high", client=None)
    with pytest.raises(RuntimeError, match="not initialized"):
        await provider.generate(prompt="hi", history=[])


@pytest.mark.asyncio
async def test_claude_generate_success():
    provider = ClaudeProvider(model_name="claude-sonnet-4-6", api_key="fake")
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="claude reply")]

    with patch.object(provider.client.messages, "create", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_resp
        reply = await provider.generate(prompt="hi", history=[])
        assert reply == "claude reply"
        mock_create.assert_awaited_once()


@pytest.mark.asyncio
async def test_claude_generate_with_image():
    provider = ClaudeProvider(model_name="claude-haiku-4-5", api_key="fake")
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="img reply")]
    with patch.object(provider.client.messages, "create", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_resp
        img_b64 = base64.b64encode(b"img").decode()
        reply = await provider.generate(
            prompt="describe",
            history=[],
            image_data={"data": img_b64, "mime_type": "image/jpeg"},
        )
        assert reply == "img reply"
        # Verify image was passed correctly
        sent_messages = mock_create.call_args.kwargs["messages"]
        user_content = sent_messages[-1]["content"]
        assert any(c["type"] == "image" for c in user_content)


@pytest.mark.asyncio
async def test_claude_stream():
    provider = ClaudeProvider(model_name="claude-sonnet-4-6", api_key="fake")
    mock_stream = AsyncMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=None)
    mock_stream.text_stream = AsyncMock()
    # Make text_stream an async iterable
    async def gen():
        for t in ["a", "b"]:
            yield t

    mock_stream.text_stream = gen()
    with patch.object(provider.client.messages, "stream", return_value=mock_stream):
        chunks = []
        async for c in provider.generate_stream(prompt="hi", history=[]):
            chunks.append(c)
        assert chunks == ["a", "b"]


@pytest.mark.asyncio
async def test_provider_retry_not_on_ratelimit():
    """Ensure RateLimitError is not retried (via tenacity). We test by checking provider raises directly."""
    from openai import RateLimitError

    mock_client = AsyncMock()
    # Simulate RateLimitError on create
    mock_client.responses.create.side_effect = RateLimitError(
        message="rate limit", response=MagicMock(status_code=429), body=None
    )
    provider = OpenAIProvider(model_name="gpt-5.4-mini", client=mock_client)
    with pytest.raises(RateLimitError):
        await provider.generate(prompt="hi", history=[])
    # Should have been called only once (no retry)
    assert mock_client.responses.create.call_count == 1
