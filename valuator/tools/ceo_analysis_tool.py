from __future__ import annotations

from typing import Any

from ..models.gemini_direct import GeminiClient
from ..utils.config import config
from .base import BaseTool, ToolResult
from .domain_prompts import ceo_analysis_system


class CEOAnalysisTool(BaseTool):
    def __init__(self, usage_writer: Any | None = None):
        super().__init__(
            name="ceo_analysis_tool",
            description="Evaluate CEO and leadership quality for long-term investment decisions.",
        )
        self.client = GeminiClient(config.agent_model, usage_writer=usage_writer)

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.client.bind_usage_writer(usage_writer)

    async def analyze_as_ceo(self, corp: str, context: str = "") -> str:
        """
        Evaluate a public company from a long-term investor perspective.

        Focus:
        - CEO and senior leadership quality
        - Organizational culture and governance

        Args:
            corp: Company name

        Returns:
            Leadership and culture analysis report in markdown text.
        """
        prompt = f"[Company Name]\n{corp}\n\n[Context]\n{context or '(none)'}\n"
        return await self.client.generate(
            prompt=prompt,
            system_prompt=ceo_analysis_system,
            trace_method="ceo_analysis_tool.analyze_as_ceo",
        )

    async def execute(self, **kwargs) -> ToolResult:
        corp = str(kwargs.get("corp") or kwargs.get("company_name") or kwargs.get("ticker") or "").strip()
        query = str(kwargs.get("query") or "").strip()
        context = str(kwargs.get("context") or "").strip()
        if not corp and not query:
            return ToolResult(success=False, result=None, error="'corp' or 'query' is required")
        if not corp:
            corp = query

        report = await self.analyze_as_ceo(corp, context=context)
        normalized_report = report.strip()
        return ToolResult(
            success=True,
            result={
                "corp": corp,
                "findings": normalized_report,
            },
            metadata={"tool_type": "domain", "domain": "ceo"},
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
                        "corp": {"type": "string"},
                        "company_name": {"type": "string"},
                        "query": {"type": "string"},
                        "ticker": {"type": "string"},
                        "context": {"type": "string"},
                    },
                    "required": [],
                },
            },
        }
