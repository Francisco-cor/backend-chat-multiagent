import base64
import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

# IMPORTACIÓN DEL NUEVO SDK 2025
from google import genai
from google.genai import types

from openai import OpenAI
from app.db.models import ConversationHistory

# Sistema Prompt global
SYSTEM_INSTRUCTION = """
Eres una secretaria virtual profesional llamada 'Clara'. 
Te comunicas en español o inglés. Sé concisa, proactiva y útil.
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
        # Inicialización del cliente unificado 2025
        self.client = genai.Client(api_key=api_key)
        
    def _format_content(self, history: List[ConversationHistory]) -> List[types.Content]:
        """
        Convierte historial DB a objetos types.Content del nuevo SDK.
        """
        contents = []
        for m in history:
            # Mapeo de roles: 'model' en BD -> 'model' en API, 'user' -> 'user'
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
        
        # 1. Configuración de Herramientas (Grounding 2025)
        tools_config = []
        if use_search:
            # Sintaxis nueva para Google Search
            tools_config = [types.Tool(google_search=types.GoogleSearch())]

        # 2. Configuración de Generación
        config = types.GenerateContentConfig(
            temperature=0.7,
            system_instruction=SYSTEM_INSTRUCTION, # Se pasa en config, no en historial
            tools=tools_config,
            safety_settings=[
                types.SafetySetting(
                    category="HARM_CATEGORY_HARASSMENT",
                    threshold="BLOCK_ONLY_HIGH"
                )
            ]
        )

        # 3. Construir el historial + mensaje actual
        # El nuevo SDK es stateless por defecto si usamos models.generate_content
        # así que pasamos todo el contexto como 'contents'.
        contents = self._format_content(history)
        
        # Crear partes del mensaje actual del usuario
        current_parts = [types.Part.from_text(text=prompt)]
        
        # Manejo Multimodal (Nuevo SDK maneja bytes raw o base64)
        if image_data:
            # Decodificamos base64 a bytes
            img_bytes = base64.b64decode(image_data["data"])
            current_parts.append(
                types.Part.from_bytes(
                    data=img_bytes, 
                    mime_type=image_data["mime_type"]
                )
            )
        elif file_data:
            file_bytes = base64.b64decode(file_data["data"])
            current_parts.append(
                types.Part.from_bytes(
                    data=file_bytes,
                    mime_type=file_data["mime_type"]
                )
            )

        # Añadimos el mensaje actual al final
        contents.append(types.Content(role="user", parts=current_parts))

        # 4. Llamada Asíncrona (wrappeada en hilo o nativa si el SDK lo soporta)
        # Nota: En v1.51, generate_content es sincrónico o tiene versión async separada.
        # Usamos aio.to_thread para garantizar no bloqueo si usamos la llamada sync estándar,
        # o client.aio.models.generate_content si usamos el cliente async.
        # Asumiremos cliente estándar wrappeado para máxima compatibilidad.
        
        def _call_sync():
            return self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config
            )

        response = await asyncio.to_thread(_call_sync)

        # 5. Extracción de texto (Grounding puede devolver partes sin texto si solo cita)
        if response.text:
            return response.text.strip()
        
        # Fallback si la respuesta es puramente metadata o tool usage (raro en chat puro)
        return "Información procesada, pero no se generó texto verbal."


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
             raw = base64.b64decode(file_data["data"]).decode("utf-8", errors="ignore")[:5000]
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
            # Extracción para SDK >= 1.120
            return getattr(resp, "output_text", "") or resp.choices[0].message.content or ""
        except Exception:
            return "Error OpenAI Generation."