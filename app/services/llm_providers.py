import base64
import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

# IMPORT OF THE NEW 2025 SDK
from google import genai
from google.genai import types

from openai import AsyncOpenAI, APIConnectionError, RateLimitError, APIStatusError
import anthropic
from app.db.models import ConversationHistory

# Global System Prompt
SYSTEM_INSTRUCTION = """
You are a professional virtual assistant named 'Clara'.
You communicate in Spanish or English. Be concise, proactive, and helpful.
"""

class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        history: List[ConversationHistory],
        image_data: Optional[Dict[str, str]] = None,
        file_data: Optional[Dict[str, str]] = None,
        use_search: bool = False,
    ) -> str:
        pass

    async def generate_stream(
        self,
        prompt: str,
        history: List[ConversationHistory],
        image_data: Optional[Dict[str, str]] = None,
        file_data: Optional[Dict[str, str]] = None,
        use_search: bool = False,
    ):
        """Default: yield the full response as a single chunk (non-streaming fallback)."""
        result = await self.generate(prompt, history, image_data, file_data, use_search)
        yield result

class GoogleGeminiProvider(LLMProvider):
    def __init__(self, model_name: str, api_key: str):
        self.model_name = model_name
        # Initialization of the unified 2025 client
        self.client = genai.Client(api_key=api_key)
        
    def _format_content(self, history: List[ConversationHistory]) -> List[types.Content]:
        """
        Converts DB history to types.Content objects for the new SDK.
        """
        contents = []
        for m in history:
            # Role mapping: 'model' in DB -> 'model' in API, 'user' -> 'user'
            contents.append(
                types.Content(
                    role=m.role,
                    parts=[types.Part.from_text(text=m.content)]
                )
            )
        return contents

    async def generate(
        self,
        prompt: str,
        history: List[ConversationHistory],
        image_data: Optional[Dict[str, str]] = None,
        file_data: Optional[Dict[str, str]] = None,
        use_search: bool = False
    ) -> str:
        
        # 1. Tool Configuration (Grounding 2025)
        tools_config = []
        if use_search:
            # New syntax for Google Search
            tools_config = [types.Tool(google_search=types.GoogleSearch())]

        # 2. Generation Configuration
        config = types.GenerateContentConfig(
            temperature=0.7,
            system_instruction=SYSTEM_INSTRUCTION, # Passed in config, not in history
            tools=tools_config,
            safety_settings=[
                types.SafetySetting(
                    category="HARM_CATEGORY_HARASSMENT",
                    threshold="BLOCK_ONLY_HIGH"
                )
            ]
        )

        # 3. Build history + current message
        # The new SDK is stateless by default if using models.generate_content
        # so we pass the entire context as 'contents'.
        contents = self._format_content(history)
        
        # Create current user message parts
        current_parts = [types.Part.from_text(text=prompt)]
        
        # Multimodal handling (New SDK handles raw bytes or base64)
        if image_data:
            # Decode base64 to bytes asynchronously
            img_bytes = await asyncio.to_thread(base64.b64decode, image_data["data"])
            current_parts.append(
                types.Part.from_bytes(
                    data=img_bytes, 
                    mime_type=image_data["mime_type"]
                )
            )
        elif file_data:
            file_bytes = await asyncio.to_thread(base64.b64decode, file_data["data"])
            current_parts.append(
                types.Part.from_bytes(
                    data=file_bytes,
                    mime_type=file_data["mime_type"]
                )
            )

        # Append current message at the end
        contents.append(types.Content(role="user", parts=current_parts))

        # 4. Asynchronous Call (wrapped in thread for the synchronous SDK call)
        # Note: In v1.51, generate_content has a sync version.
        # We use aio.to_thread to ensure no blocking.
        
        def _call_sync():
            return self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config
            )

        try:
            response = await asyncio.to_thread(_call_sync)

            # 5. Text extraction (Grounding might return parts without text)
            if response.text:
                return response.text.strip()
            
            # Fallback for purely metadata or tool usage responses
            return "Processed information, but no verbal text was generated."
            
        except Exception as e:
            # Capture Google GenAI errors
            raise RuntimeError(f"Google GenAI Error: {str(e)}")

    async def generate_stream(
        self,
        prompt: str,
        history: List[ConversationHistory],
        image_data: Optional[Dict[str, str]] = None,
        file_data: Optional[Dict[str, str]] = None,
        use_search: bool = False,
    ):
        tools_config = [types.Tool(google_search=types.GoogleSearch())] if use_search else []
        config = types.GenerateContentConfig(
            temperature=0.7,
            system_instruction=SYSTEM_INSTRUCTION,
            tools=tools_config,
            safety_settings=[
                types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_ONLY_HIGH")
            ],
        )
        contents = self._format_content(history)
        current_parts = [types.Part.from_text(text=prompt)]
        if image_data:
            img_bytes = await asyncio.to_thread(base64.b64decode, image_data["data"])
            current_parts.append(types.Part.from_bytes(data=img_bytes, mime_type=image_data["mime_type"]))
        elif file_data:
            file_bytes = await asyncio.to_thread(base64.b64decode, file_data["data"])
            current_parts.append(types.Part.from_bytes(data=file_bytes, mime_type=file_data["mime_type"]))
        contents.append(types.Content(role="user", parts=current_parts))

        try:
            async for chunk in self.client.aio.models.generate_content_stream(
                model=self.model_name, contents=contents, config=config
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            raise RuntimeError(f"Google GenAI Stream Error: {str(e)}")


class OpenAIProvider(LLMProvider):
    def __init__(self, model_name: str, client: AsyncOpenAI):
        # Map model alias to reasoning effort and base model name.
        # e.g. "gpt-5.4-mini" → effort="low", model="gpt-5.4"
        if "mini" in model_name:
            self.effort = "low"
        elif "medium" in model_name:
            self.effort = "medium"
        else:
            self.effort = "high"
        self.model_name = (
            model_name
            .replace("-mini", "")
            .replace("-medium", "")
            .replace("-high", "")
            .strip()
        )
        self.client = client

    def _format_history(self, history: List[ConversationHistory]) -> List[Dict[str, Any]]:
        # Responses API: system message uses plain string content
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_INSTRUCTION.strip()}
        ]
        for m in history:
            role = "assistant" if m.role == "model" else "user"
            messages.append({"role": role, "content": m.content})
        return messages

    async def generate(
        self,
        prompt: str,
        history: List[ConversationHistory],
        image_data: Optional[Dict[str, str]] = None,
        file_data: Optional[Dict[str, str]] = None,
        use_search: bool = False
    ) -> str:
        if not self.client:
            raise RuntimeError("OpenAI Client not initialized.")

        messages = self._format_history(history)
        
        user_content = [{"type": "input_text", "text": prompt}]
        
        if image_data:
            user_content.append({"type": "input_image", "image_base64": image_data["data"]})
        
        if file_data and file_data["mime_type"].startswith("text/"):
             # Decode and decode string in a thread to prevent blocking
             raw = await asyncio.to_thread(
                 lambda: base64.b64decode(file_data["data"]).decode("utf-8", errors="ignore")[:5000]
             )
             user_content.append({"type": "input_text", "text": f"File Content:\n{raw}"})

        messages.append({"role": "user", "content": user_content})

        # Responses API (GPT-5 / o-series) — async client, no asyncio.to_thread needed
        try:
            resp = await self.client.responses.create(
                model=self.model_name,
                input=messages,
                reasoning={"effort": self.effort},
            )
            return resp.output_text or ""
        except RateLimitError:
            raise
        except APIConnectionError:
            raise
        except APIStatusError as e:
            raise RuntimeError(f"OpenAI API Error: {e.status_code} - {e.message}")
        except Exception as e:
            raise RuntimeError(f"Unexpected OpenAI Error: {str(e)}")

    async def generate_stream(
        self,
        prompt: str,
        history: List[ConversationHistory],
        image_data: Optional[Dict[str, str]] = None,
        file_data: Optional[Dict[str, str]] = None,
        use_search: bool = False,
    ):
        messages = self._format_history(history)
        user_content = [{"type": "input_text", "text": prompt}]
        if image_data:
            user_content.append({"type": "input_image", "image_base64": image_data["data"]})
        if file_data and file_data["mime_type"].startswith("text/"):
            raw = base64.b64decode(file_data["data"]).decode("utf-8", errors="ignore")[:5000]
            user_content.append({"type": "input_text", "text": f"File Content:\n{raw}"})
        messages.append({"role": "user", "content": user_content})

        try:
            async with self.client.responses.stream(
                model=self.model_name,
                input=messages,
                reasoning={"effort": self.effort},
            ) as stream:
                async for event in stream:
                    delta = getattr(event, "output_text_delta", None)
                    if delta:
                        yield delta
        except RateLimitError:
            raise
        except APIConnectionError:
            raise
        except APIStatusError as e:
            raise RuntimeError(f"OpenAI Stream Error: {e.status_code} - {e.message}")
        except Exception as e:
            raise RuntimeError(f"Unexpected OpenAI Stream Error: {str(e)}")


class ClaudeProvider(LLMProvider):
    def __init__(self, model_name: str, api_key: str):
        self.model_name = model_name
        # Map short alias to real Anthropic model ID
        _model_map = {
            "claude-sonnet-4-6": "claude-sonnet-4-6",
            "claude-haiku-4-5":  "claude-haiku-4-5-20251001",
        }
        self.model_id = _model_map.get(model_name, model_name)
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    def _format_history(self, history: List[ConversationHistory]) -> List[Dict[str, Any]]:
        messages = []
        for m in history:
            role = "assistant" if m.role == "model" else "user"
            messages.append({"role": role, "content": m.content})
        return messages

    async def generate(
        self,
        prompt: str,
        history: List[ConversationHistory],
        image_data: Optional[Dict[str, str]] = None,
        file_data: Optional[Dict[str, str]] = None,
        use_search: bool = False,
    ) -> str:
        messages = self._format_history(history)

        user_content: List[Dict[str, Any]] = []

        if image_data:
            user_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_data["mime_type"],
                    "data": image_data["data"],
                },
            })

        if file_data and file_data["mime_type"].startswith("text/"):
            raw = base64.b64decode(file_data["data"]).decode("utf-8", errors="ignore")[:5000]
            user_content.append({"type": "text", "text": f"File Content:\n{raw}"})

        user_content.append({"type": "text", "text": prompt})
        messages.append({"role": "user", "content": user_content})

        try:
            response = await self.client.messages.create(
                model=self.model_id,
                max_tokens=8096,
                system=SYSTEM_INSTRUCTION.strip(),
                messages=messages,
            )
            return response.content[0].text
        except (anthropic.RateLimitError, anthropic.APIConnectionError):
            raise  # Caught by service layer
        except anthropic.APIStatusError as e:
            raise RuntimeError(f"Claude API Error: {e.status_code} - {e.message}")
        except Exception as e:
            raise RuntimeError(f"Unexpected Claude Error: {str(e)}")

    async def generate_stream(
        self,
        prompt: str,
        history: List[ConversationHistory],
        image_data: Optional[Dict[str, str]] = None,
        file_data: Optional[Dict[str, str]] = None,
        use_search: bool = False,
    ):
        messages = self._format_history(history)
        user_content: List[Dict[str, Any]] = []
        if image_data:
            user_content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": image_data["mime_type"], "data": image_data["data"]},
            })
        if file_data and file_data["mime_type"].startswith("text/"):
            raw = base64.b64decode(file_data["data"]).decode("utf-8", errors="ignore")[:5000]
            user_content.append({"type": "text", "text": f"File Content:\n{raw}"})
        user_content.append({"type": "text", "text": prompt})
        messages.append({"role": "user", "content": user_content})

        try:
            async with self.client.messages.stream(
                model=self.model_id,
                max_tokens=8096,
                system=SYSTEM_INSTRUCTION.strip(),
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except (anthropic.RateLimitError, anthropic.APIConnectionError):
            raise
        except anthropic.APIStatusError as e:
            raise RuntimeError(f"Claude Stream Error: {e.status_code} - {e.message}")
        except Exception as e:
            raise RuntimeError(f"Unexpected Claude Stream Error: {str(e)}")
