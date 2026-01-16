import asyncio
from dataclasses import dataclass

from google import genai
from google.genai import types

from ..utils.config import config


@dataclass
class GeminiResponse:
    content: str


class GeminiSession:
    def __init__(
        self,
        client: genai.Client,
        model: str,
        system_prompt: str,
        response_mime_type: str | None,
        response_schema: dict | None,
        response_json_schema: dict | None,
    ):
        self.client = client
        self.model = model
        self.system_prompt = system_prompt
        self.response_mime_type = response_mime_type
        self.response_schema = response_schema
        self.response_json_schema = response_json_schema

    async def send_message(self, prompt: str) -> GeminiResponse:
        def _call():
            cfg = {}
            if self.system_prompt:
                cfg["systemInstruction"] = self.system_prompt
            if self.response_mime_type:
                cfg["responseMimeType"] = self.response_mime_type
            if self.response_schema:
                cfg["responseSchema"] = self.response_schema
            if self.response_json_schema:
                cfg["responseJsonSchema"] = self.response_json_schema
            config = types.GenerateContentConfig(**cfg) if cfg else None
            return self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )

        response = await asyncio.to_thread(_call)
        text = getattr(response, "text", "") or ""
        return GeminiResponse(content=text)


class Gemini3Client:
    def __init__(self, model: str | None = None, api_key: str | None = None):
        key = api_key or config.google_api_key
        if not key:
            raise ValueError("Missing GOOGLE_API_KEY or GEMINI_API_KEY")
        self.model = model or config.agent_model
        self.client = genai.Client(api_key=key)

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        response_mime_type: str | None = None,
        response_schema: dict | None = None,
        response_json_schema: dict | None = None,
    ) -> str:
        session = GeminiSession(
            self.client,
            self.model,
            system_prompt,
            response_mime_type,
            response_schema,
            response_json_schema,
        )
        response = await session.send_message(prompt)
        text = response.content.strip()
        if not text:
            raise ValueError("Empty response from Gemini")
        return text
