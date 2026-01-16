import asyncio
from dataclasses import dataclass

from google import genai
from google.genai import types

from ..utils.config import config


@dataclass
class GeminiResponse:
    content: str


class GeminiSession:
    def __init__(self, client: genai.Client, model: str, system_prompt: str):
        self.client = client
        self.model = model
        self.system_prompt = system_prompt

    async def send_message(self, prompt: str) -> GeminiResponse:
        def _call():
            config = (
                types.GenerateContentConfig(systemInstruction=self.system_prompt)
                if self.system_prompt
                else None
            )
            return self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )

        response = await asyncio.to_thread(_call)
        text = getattr(response, "text", "") or ""
        if not text:
            raise ValueError("Empty response from Gemini")
        return GeminiResponse(content=text)


class GeminiModel:
    def __init__(self, model: str | None = None, api_key: str | None = None):
        key = api_key or config.google_api_key
        if not key:
            raise ValueError("Missing GOOGLE_API_KEY")
        self.model = model or config.agent_model
        self.client = genai.Client(api_key=key)

    def format_messages(self, system_prompt: str) -> dict:
        return {"system_prompt": system_prompt}

    def start_chat_session(self, messages: dict) -> GeminiSession:
        system_prompt = messages.get("system_prompt", "")
        return GeminiSession(self.client, self.model, system_prompt)
