from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..models.gemini_direct import GeminiClient
from ..utils.config import config
from .base import BaseTool, ToolResult
from .domain_prompts import balance_sheet_extraction

_EXTRACTION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["balance_sheet", "units"],
    "properties": {
        "units": {"type": "string"},
        "as_of": {"type": "string"},
        "balance_sheet": {
            "type": "object",
            "additionalProperties": False,
            "required": ["assets", "liabilities", "equity"],
            "properties": {
                "assets": {"$ref": "#/definitions/section"},
                "liabilities": {"$ref": "#/definitions/section"},
                "equity": {"$ref": "#/definitions/section"},
            },
        },
    },
    "definitions": {
        "component": {
            "type": "object",
            "additionalProperties": False,
            "required": ["item", "value"],
            "properties": {
                "item": {"type": "string"},
                "value": {"type": "string"},
            },
        },
        "section": {
            "type": "object",
            "additionalProperties": False,
            "required": ["total", "components"],
            "properties": {
                "total": {"type": "string"},
                "components": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/component"},
                },
            },
        },
    },
}


class BalanceSheetExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    summary: str = Field(min_length=1)


class BalanceSheetExtractionTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            name="balance_sheet_extraction_tool",
            description="Extract normalized balance-sheet JSON from summary text.",
        )
        self.client = GeminiClient(config.agent_model)

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.client.bind_usage_writer(usage_writer)

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            request = BalanceSheetExtractionRequest.model_validate(
                {"summary": kwargs.get("summary")}
            )
        except ValidationError as exc:
            return ToolResult(success=False, result=None, error=str(exc))

        try:
            extracted = await self._extract_from_summary(request.summary)
        except Exception as exc:
            return ToolResult(success=False, result=None, error=str(exc))

        return ToolResult(
            success=True,
            result={
                "balance_sheet": extracted["balance_sheet"],
                "units": extracted["units"],
                "as_of": extracted.get("as_of"),
                "findings": "balance-sheet extracted from provided summary text",
            },
            metadata={"tool_type": "domain", "domain": "balance_sheet"},
        )

    async def _extract_from_summary(self, summary: str) -> dict[str, Any]:
        prompt = balance_sheet_extraction.format(summary=summary)
        return await self.client.generate_json(
            prompt=prompt,
            system_prompt="Return concise JSON only.",
            response_json_schema=_EXTRACTION_RESPONSE_SCHEMA,
            trace_method="balance_sheet_extraction_tool._extract_from_summary",
        )

    def get_schema(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Financial summary text to extract balance-sheet JSON from.",
                        }
                    },
                    "required": ["summary"],
                },
            },
        }
