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
        grounding_mode = (
            str(kwargs.get("grounding_mode") or "grounded_required").strip().lower()
        )
        if grounding_mode not in {"grounded_required", "synthesis_only"}:
            return ToolResult(
                success=False,
                result=None,
                error="grounding_mode must be 'grounded_required' or 'synthesis_only'",
            )
        guide = str(kwargs.get("domain_guide") or "").strip()
        persona = str(kwargs.get("domain_persona") or "").strip()
        rubric = str(kwargs.get("domain_rubric") or "").strip()
        format_spec = str(kwargs.get("domain_format") or "").strip()
        corp = corp or query
        context = str(kwargs.get("context") or "").strip()
        as_of_utc = str(kwargs.get("as_of_utc") or "").strip()
        time_scope = str(kwargs.get("time_scope") or "").strip().lower()
        target_start = str(kwargs.get("target_start") or "").strip()
        target_end = str(kwargs.get("target_end") or "").strip()
        if grounding_mode == "grounded_required" and not context:
            return ToolResult(
                success=False,
                result=None,
                error="grounded_required mode requires non-empty context",
            )
        system_prompt = (
            persona
            or guide
            or "당신은 근거 기반 분석만 수행하는 기업 가치 분석가입니다."
        )
        prompt = (
            f"[ANALYSIS_TARGET]\n{corp}\n\n"
            f"[GROUNDING_MODE]\n{grounding_mode}\n\n"
            f"[AS_OF_UTC]\n{as_of_utc or '(unknown)'}\n\n"
            f"[TIME_SCOPE]\n{time_scope or '(none)'}\n\n"
            "[TARGET_PERIOD]\n"
            f"{target_start or '(open)'}..{target_end or '(open)'}\n\n"
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
            "grounded_required 모드에서는 [CONTEXT]에 없는 사건, 날짜, 수치, 현재 사실을 생성하지 마라.\n"
            "grounded=false 또는 미검증 정보는 가정, 불확실성, 추가 확인 필요로만 다뤄라.\n"
            "historical 범위는 [TARGET_PERIOD] 안의 사실만 서술하라.\n"
            "current 범위의 현재 진술은 [AS_OF_UTC] 기준으로만 작성하라.\n"
            "synthesis_only 모드에서는 미래 시나리오 조합은 허용하지만, 현재/과거 사실을 단정하지 마라.\n"
        )
        report = await self.client.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            trace_method="domain_tool.aspect_guided",
        )
        return ToolResult(
            success=True,
            result={
                "corp": corp,
                "findings": report.strip(),
                "grounding_mode": grounding_mode,
                "as_of_utc": as_of_utc,
                "time_scope": time_scope,
                "target_start": target_start,
                "target_end": target_end,
            },
            metadata={
                "tool_type": "domain",
                "domain": str(kwargs.get("domain_id") or "").strip(),
                "grounding_mode": grounding_mode,
                "as_of_utc": as_of_utc,
                "time_scope": time_scope,
                "target_start": target_start,
                "target_end": target_end,
            },
        )

    def _corp(self, kwargs: dict[str, Any]) -> str:
        return str(
            kwargs.get("corp")
            or kwargs.get("company_name")
            or kwargs.get("ticker")
            or ""
        ).strip()
