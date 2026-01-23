import base64
import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

# IMPORT OF THE NEW 2025 SDK
from google import genai
from google.genai import types

from openai import OpenAI, APIConnectionError, RateLimitError, APIStatusError
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
        use_search: bool = False
    ) -> str:
        pass

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


class OpenAIProvider(LLMProvider):
    def __init__(self, model_name: str, client: OpenAI):
        self.model_name = "gpt-5" 
        self.effort = "low" if "low" in model_name else "high"
        self.client = client

    def _format_history(self, history: List[ConversationHistory]) -> List[Dict[str, Any]]:
        messages = [
            {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_INSTRUCTION}]}
        ]
        for m in history:
            role = "assistant" if m.role == "model" else "user"
            ctype = "output_text" if role == "assistant" else "input_text"
            messages.append({"role": role, "content": [{"type": ctype, "text": m.content}]})
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

        # Responses API (GPT-5)
        try:
            resp = await asyncio.to_thread(
                self.client.responses.create,
                model=self.model_name,
                input=messages,
                reasoning={"effort": self.effort}
            )
            # Extraction for SDK >= 1.120
            return getattr(resp, "output_text", "") or resp.choices[0].message.content or ""
        except RateLimitError:
            raise  # Re-raise for service layer to handle (429)
        except APIConnectionError:
            raise  # Re-raise for service layer to handle (503)
        except APIStatusError as e:
            raise RuntimeError(f"OpenAI API Error: {e.status_code} - {e.message}")
        except Exception as e:
            raise RuntimeError(f"Unexpected OpenAI Error: {str(e)}")
