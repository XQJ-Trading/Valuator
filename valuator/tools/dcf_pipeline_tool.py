from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ..models.gemini_direct import GeminiClient
from ..utils.config import config
from .base import BaseTool, ToolResult
from .code_execute_tool import ExecuteCodeTool
from .dcf_model import build_dcf_calculation_code
from .domain_prompts import (
    calculate_dcf_system,
    create_dcf_form_system,
    fill_dcf_form_system,
)


class DCFPipelineTool(BaseTool):
    def __init__(self, usage_writer: Any | None = None):
        super().__init__(
            name="dcf_pipeline_tool",
            description="Run DCF pipeline: create form, fill form, calculate valuation.",
        )
        self.client = GeminiClient(config.agent_model, usage_writer=usage_writer)
        self.code_tool = ExecuteCodeTool()

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.client.bind_usage_writer(usage_writer)
        self.code_tool.bind_usage_writer(usage_writer)

    async def execute(self, **kwargs) -> ToolResult:
        company_name = str(
            kwargs.get("corp")
            or kwargs.get("company_name")
            or kwargs.get("ticker")
            or ""
        ).strip()
        query = str(kwargs.get("query") or "").strip()
        context = str(kwargs.get("context") or "").strip()
        if not company_name and not query:
            return ToolResult(
                success=False,
                result=None,
                error="'company_name' or 'query' is required",
            )
        if not company_name:
            company_name = query

        form_markdown = await self._create_dcf_form(company_name=company_name)
        filled_form = await self._fill_dcf_form(
            company_name=company_name,
            form_markdown=form_markdown,
            context=context,
        )
        assumptions = await self._extract_assumptions(
            company_name=company_name,
            filled_form=filled_form,
        )
        calculation = await self._calculate_dcf(assumptions=assumptions)
        if not calculation.success:
            return ToolResult(
                success=False,
                result={
                    "company_name": company_name,
                    "form": form_markdown,
                    "filled_form": filled_form,
                    "assumptions": assumptions,
                    "calculation": calculation.result,
                },
                error=calculation.error,
                metadata=calculation.metadata,
            )

        valuation_summary = (
            await self._summarize_valuation(
                company_name=company_name,
                filled_form=filled_form,
                assumptions=assumptions,
                calculation_result=calculation,
                context=context,
            )
        ).strip()

        return ToolResult(
            success=True,
            result={
                "company_name": company_name,
                "form": form_markdown,
                "filled_form": filled_form,
                "assumptions": assumptions,
                "calculation": calculation.result,
                "findings": valuation_summary,
            },
            metadata={"tool_type": "domain", "domain": "dcf"},
        )

    async def _create_dcf_form(self, *, company_name: str) -> str:
        system_prompt = create_dcf_form_system.format(company_name=company_name)
        return await self.client.generate(
            prompt="Design a spreadsheet-style DCF template for 15 forecast years.",
            system_prompt=system_prompt,
            trace_method="dcf_pipeline_tool._create_dcf_form",
        )

    async def _fill_dcf_form(
        self,
        *,
        company_name: str,
        form_markdown: str,
        context: str,
    ) -> str:
        today = datetime.utcnow().date().isoformat()
        system_prompt = fill_dcf_form_system.format(
            company_name=company_name,
            today=today,
        )
        prompt = (
            "Fill the DCF form below with researched values.\n"
            "If a complex calculation is required, keep it as a math expression.\n\n"
            f"[CONTEXT]\n{context or '(none)'}\n\n"
            f"[DCF_FORM]\n{form_markdown}\n"
        )
        return await self.client.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            trace_method="dcf_pipeline_tool._fill_dcf_form",
        )

    async def _extract_assumptions(
        self, *, company_name: str, filled_form: str
    ) -> dict[str, Any]:
        prompt = (
            "Extract normalized DCF assumptions from the filled form.\n"
            "Return JSON only with required numeric fields.\n\n"
            f"[COMPANY]\n{company_name}\n\n"
            f"[FILLED_DCF_FORM]\n{filled_form}\n"
        )
        data = await self.client.generate_json(
            prompt=prompt,
            system_prompt="Return concise JSON only.",
            response_json_schema={
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "base_revenue",
                    "growth_rate",
                    "op_margin",
                    "tax_rate",
                    "reinvestment_rate",
                    "discount_rate",
                    "terminal_growth",
                    "projection_years",
                ],
                "properties": {
                    "base_revenue": {"type": "number"},
                    "growth_rate": {"type": "number"},
                    "op_margin": {"type": "number"},
                    "tax_rate": {"type": "number"},
                    "reinvestment_rate": {"type": "number"},
                    "discount_rate": {"type": "number"},
                    "terminal_growth": {"type": "number"},
                    "projection_years": {"type": "integer", "minimum": 1},
                },
            },
            trace_method="dcf_pipeline_tool._extract_assumptions",
        )
        return data

    async def _calculate_dcf(self, *, assumptions: dict[str, Any]) -> ToolResult:
        code = build_dcf_calculation_code(assumptions=assumptions)
        return await self.code_tool.execute(code=code)

    async def _summarize_valuation(
        self,
        *,
        company_name: str,
        filled_form: str,
        assumptions: dict[str, Any],
        calculation_result: ToolResult,
        context: str,
    ) -> str:
        calc_output = ""
        if calculation_result.result and isinstance(calculation_result.result, dict):
            calc_output = calculation_result.result.get("output", "") or ""
        prompt = (
            f"[COMPANY]\n{company_name}\n\n"
            f"[CONTEXT]\n{context or '(none)'}\n\n"
            f"[FILLED_FORM]\n{filled_form}\n\n"
            f"[ASSUMPTIONS]\n{json.dumps(assumptions, ensure_ascii=False)}\n\n"
            f"[DCF_CALCULATION_OUTPUT]\n{calc_output}\n"
        )
        return await self.client.generate(
            prompt=prompt,
            system_prompt=calculate_dcf_system,
            trace_method="dcf_pipeline_tool._summarize_valuation",
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
                    },
                    "required": [],
                },
            },
        }
