from __future__ import annotations

from typing import Any

from ..utils.config import config
from .base import BaseTool, ToolResult


class DomainTool(BaseTool):
    def __init__(self, usage_writer: Any | None = None, model: str | None = None):
        super().__init__(
            name="domain_tool",
            description="Execute guide-based domain analysis.",
        )
        from ..models.gemini_direct import GeminiClient as RuntimeGeminiClient

        self.client = RuntimeGeminiClient(
            model or config.agent_model,
            usage_writer=usage_writer,
        )

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.client.bind_usage_writer(usage_writer)

    async def execute(self, **kwargs: Any) -> ToolResult:
        corp = self._corp(kwargs)
        query = str(kwargs.get("query") or "").strip()
        if not corp and not query:
            return ToolResult(success=False, result=None, error="'corp' or 'query' is required")
        guide = str(kwargs.get("domain_guide") or "").strip()
        persona = str(kwargs.get("domain_persona") or "").strip()
        rubric = str(kwargs.get("domain_rubric") or "").strip()
        format_spec = str(kwargs.get("domain_format") or "").strip()
        corp = corp or query
        context = str(kwargs.get("context") or "").strip()
        system_prompt = persona or guide or "당신은 기업 가치 분석가입니다."
        prompt = (
            f"[ANALYSIS_TARGET]\n{corp}\n\n"
            f"[RUBRIC_ASPECTS]\n{rubric or '(none)'}\n\n"
            f"[FORMAT]\n{format_spec or '(none)'}\n\n"
            f"[CONTEXT]\n{context or '(none)'}\n\n"
            "[INSTRUCTION]\n"
            "각 aspect별로 `### [ASPECT:{aspect_id}]` 헤더 아래 분석을 작성하라.\n"
            "정량 데이터는 Markdown 표로 정리하라. 표에는 연도, 수치, 변화율을 포함하라.\n"
            "정량 데이터와 절대 시점은 그대로 유지하라.\n"
            "[CONTEXT]의 표, 좌표계, 임계치, 비교 블록이 있으면 관련 aspect 아래에서 구조를 최대한 유지하라.\n"
            "페르소나 해석을 추가하되, [CONTEXT]의 고유 사실을 일반론으로 치환하거나 삭제하지 마라.\n"
            "[CONTEXT]에 없는 정량 수치(금액, 비율, 날짜)는 생성하지 마라.\n"
            "정량 근거가 부족하면 '데이터 부족'으로 표시하고 필요한 추가 소스를 명시하라.\n"
        )
        report = await self.client.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            trace_method="domain_tool.aspect_guided",
        )
        return ToolResult(
            success=True,
            result={"corp": corp, "findings": report.strip()},
            metadata={"tool_type": "domain", "domain": str(kwargs.get("domain_id") or "").strip()},
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
                        "ticker": {"type": "string"},
                        "query": {"type": "string"},
                        "context": {"type": "string"},
                        "domain_id": {"type": "string"},
                        "domain_guide": {"type": "string"},
                        "domain_persona": {"type": "string"},
                        "domain_rubric": {"type": "string"},
                        "domain_format": {"type": "string"},
                    },
                    "required": [],
                },
            },
        }

    def _corp(self, kwargs: dict[str, Any]) -> str:
        return str(
            kwargs.get("corp")
            or kwargs.get("company_name")
            or kwargs.get("ticker")
            or ""
        ).strip()
