from __future__ import annotations

import unittest
from unittest.mock import patch

from valuator.models.gemini_direct import (
    GeminiClient,
    ensure_supported_google_genai_runtime,
)


class _UnsupportedGenerateContentConfig:
    def __init__(self, **kwargs: object) -> None:
        if "response_json_schema" in kwargs:
            raise ValueError("response_json_schema unsupported")
        self.kwargs = kwargs


class GeminiConfigTests(unittest.TestCase):
    def tearDown(self) -> None:
        ensure_supported_google_genai_runtime.cache_clear()

    def test_runtime_guard_accepts_project_sdk(self) -> None:
        installed_version = ensure_supported_google_genai_runtime()
        self.assertEqual(installed_version, "1.62.0")

    def test_build_config_uses_single_supported_contract(self) -> None:
        client = GeminiClient(api_key="test-key", client=object())
        config = client._build_config(
            system_prompt="Return JSON only.",
            response_mime_type="application/json",
            response_json_schema={
                "type": "object",
                "properties": {"name": {"type": "string", "minLength": 1}},
                "required": ["name"],
            },
        )

        payload = config.model_dump(exclude_none=True)
        self.assertEqual(payload["system_instruction"], "Return JSON only.")
        self.assertEqual(payload["response_mime_type"], "application/json")
        self.assertIn("response_json_schema", payload)

    def test_runtime_guard_fails_fast_without_response_json_schema_support(self) -> None:
        with patch(
            "valuator.models.gemini_direct.version",
            return_value="0.3.0",
        ), patch(
            "valuator.models.gemini_direct.types.GenerateContentConfig",
            _UnsupportedGenerateContentConfig,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Unsupported google-genai runtime",
            ):
                ensure_supported_google_genai_runtime()

