from __future__ import annotations

import json
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..domain.types import PipelineConfig, PipelineStage, StageOutput
from ..utils.config import config
from .base import BaseTool, ToolResult
from .code_execute_tool import ExecuteCodeTool

if TYPE_CHECKING:
    from ..models.gemini_direct import GeminiClient

_PLACEHOLDER_RE = re.compile(r"\{(stages\.(\w+)|corp|company_name|context|today)\}")
_STAGE_DIRECT_RE = re.compile(r"^\{stages\.(\w+)\}$")
_JSON_SYSTEM_PROMPT = "Return concise JSON only."


class DomainTool(BaseTool):
    def __init__(self, usage_writer: Any | None = None):
        super().__init__(
            name="domain_tool",
            description="Execute guide-based or pipeline-based domain analysis.",
        )
        from ..models.gemini_direct import GeminiClient as RuntimeGeminiClient

        self.client = RuntimeGeminiClient(config.agent_model, usage_writer=usage_writer)
        self.code_tool = ExecuteCodeTool()

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.client.bind_usage_writer(usage_writer)
        self.code_tool.bind_usage_writer(usage_writer)

    async def execute(self, **kwargs: Any) -> ToolResult:
        corp = self._extract_corp(kwargs)
        query = str(kwargs.get("query") or "").strip()
        context = str(kwargs.get("context") or "").strip()
        domain_id = str(kwargs.get("domain_id") or "").strip()
        pipeline_config = kwargs.get("pipeline_config")

        if not corp and not query:
            return ToolResult(
                success=False,
                result=None,
                error="'corp' or 'query' is required",
            )
        if not corp:
            corp = query

        if pipeline_config is not None:
            return await self._run_pipeline(
                corp=corp,
                context=context,
                domain_id=domain_id,
                pipeline_config=pipeline_config,
            )

        domain_guide = str(kwargs.get("domain_guide") or "").strip()
        if not domain_guide:
            return ToolResult(
                success=False,
                result=None,
                error="'domain_guide' is required for simple domain execution",
            )
        return await self._run_simple(
            corp=corp,
            context=context,
            domain_id=domain_id,
            domain_guide=domain_guide,
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
                        "pipeline_config": {"type": "object"},
                    },
                    "required": [],
                },
            },
        }

    @staticmethod
    def _extract_corp(kwargs: dict[str, Any]) -> str:
        return str(
            kwargs.get("corp")
            or kwargs.get("company_name")
            or kwargs.get("ticker")
            or ""
        ).strip()

    async def _run_simple(
        self,
        *,
        corp: str,
        context: str,
        domain_id: str,
        domain_guide: str,
    ) -> ToolResult:
        prompt = f"[Company Name]\n{corp}\n\n[Context]\n{context or '(none)'}\n"
        report = await self.client.generate(
            prompt=prompt,
            system_prompt=domain_guide,
            trace_method="domain_tool.simple",
        )
        return ToolResult(
            success=True,
            result={"corp": corp, "findings": report.strip()},
            metadata={"tool_type": "domain", "domain": domain_id},
        )

    async def _run_pipeline(
        self,
        *,
        corp: str,
        context: str,
        domain_id: str,
        pipeline_config: PipelineConfig,
    ) -> ToolResult:
        outputs: dict[str, StageOutput] = {}
        for stage in pipeline_config.stages:
            outputs[stage.id] = await self._execute_stage(
                stage,
                outputs,
                corp=corp,
                context=context,
            )

        result = self._build_result(
            pipeline_config.result_mapping,
            outputs,
            corp=corp,
            context=context,
        )
        return ToolResult(
            success=True,
            result=result,
            metadata={"tool_type": "domain", "domain": domain_id},
        )

    async def _execute_stage(
        self,
        stage: PipelineStage,
        outputs: dict[str, StageOutput],
        *,
        corp: str,
        context: str,
    ) -> StageOutput:
        system_prompt = self._resolve_template(
            stage.system_prompt_content,
            outputs,
            corp=corp,
            context=context,
        )
        user_prompt = self._resolve_template(
            stage.user_prompt,
            outputs,
            corp=corp,
            context=context,
        )
        trace_method = f"domain_tool.stage.{stage.id}"

        if stage.action == "llm":
            text = await self.client.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                trace_method=trace_method,
            )
            normalized = text.strip()
            return StageOutput(raw=normalized, text=normalized)

        if stage.action == "llm_json":
            schema = stage.output_schema_content
            if schema is None:
                raise ValueError(f"llm_json stage '{stage.id}' requires output_schema_content")
            data = await self.client.generate_json(
                prompt=user_prompt,
                system_prompt=system_prompt or _JSON_SYSTEM_PROMPT,
                response_json_schema=schema,
                trace_method=trace_method,
            )
            return StageOutput(
                raw=data,
                text=json.dumps(data, ensure_ascii=False),
            )

        code = self._build_code(stage, outputs)
        result = await self.code_tool.execute(code=code)
        if not result.success:
            raise RuntimeError(result.error or f"code stage failed: {stage.id}")
        payload = result.result if isinstance(result.result, dict) else {}
        stdout = str(payload.get("output") or "").strip()
        return StageOutput(raw={"output": stdout}, text=stdout)

    def _build_code(
        self,
        stage: PipelineStage,
        outputs: dict[str, StageOutput],
    ) -> str:
        inject_lines: list[str] = []
        for var_name, stage_id in stage.inject_vars.items():
            inject_lines.append(f"{var_name} = {repr(outputs[stage_id].raw)}")
        if not inject_lines:
            return stage.code_content
        return "\n".join([*inject_lines, stage.code_content])

    def _resolve_template(
        self,
        template: str,
        outputs: dict[str, StageOutput],
        *,
        corp: str,
        context: str,
    ) -> str:
        builtins = {
            "corp": corp,
            "company_name": corp,
            "context": context,
            "today": datetime.utcnow().date().isoformat(),
        }

        def _replace(match: re.Match[str]) -> str:
            full_key = match.group(1)
            stage_id = match.group(2)
            if stage_id is not None:
                return outputs[stage_id].text
            return builtins.get(full_key, match.group(0))

        return _PLACEHOLDER_RE.sub(_replace, template)

    def _build_result(
        self,
        mapping: dict[str, str],
        outputs: dict[str, StageOutput],
        *,
        corp: str,
        context: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, template in mapping.items():
            match = _STAGE_DIRECT_RE.match(template.strip())
            if match is not None:
                result[key] = outputs[match.group(1)].raw
                continue
            result[key] = self._resolve_template(
                template,
                outputs,
                corp=corp,
                context=context,
            )
        return result
