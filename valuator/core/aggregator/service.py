from __future__ import annotations

from datetime import date
from typing import Any

from ...models.gemini_direct import GeminiClient
from ...utils.config import config
from ..contracts.plan import Plan, Task
from ..workspace.service import Workspace
from .graph_ops import descendant_leaf_task_ids, infer_root_task_id, post_order_tasks
from .materials import collect_materials, extract_leaf_artifacts, query_unit_ids_for_leaf_tasks

_SYSTEM_PROMPT = "한글 마크다운 보고서만 반환하십시오."


class Aggregation:
    def __init__(self, client: GeminiClient | None = None):
        self.client = client or GeminiClient(config.agent_model)

    async def aggregate(
        self,
        query: str,
        plan: Plan,
        execution: dict,
        workspace: Workspace,
    ) -> dict:
        leaf_artifacts = extract_leaf_artifacts(execution)
        task_map = {task.id: task for task in plan.tasks}
        descendant_cache: dict[str, list[dict[str, str]]] = {}
        reports: dict[str, dict[str, Any]] = {}

        for task_id in post_order_tasks(plan):
            task = task_map[task_id]
            materials = collect_materials(
                task, task_map, leaf_artifacts, reports, descendant_cache,
            )
            report = await self._synthesize(task, query, materials)
            reports[task_id] = report
            workspace.write_output(
                f"/aggregation/{task_id}/report.md",
                report["markdown"],
            )

        root_task_id = plan.root_task_id or infer_root_task_id(plan.tasks)
        root_report = reports.get(root_task_id)
        if not root_report:
            raise ValueError(f"root node report is missing: {root_task_id}")

        descendant_leaf_ids = descendant_leaf_task_ids(root_task_id, task_map)
        aggregated_leaf_task_ids = sorted(
            task_id for task_id in descendant_leaf_ids if leaf_artifacts.get(task_id)
        )
        aggregated_query_unit_ids = query_unit_ids_for_leaf_tasks(aggregated_leaf_task_ids, task_map)

        final_md = await self._compose_final_report(
            query,
            plan.analysis_strategy,
            root_report["markdown"],
        )
        return {
            "final_markdown": final_md,
            "root_task_id": root_task_id,
            "root_report": root_report,
            "aggregated_leaf_task_ids": aggregated_leaf_task_ids,
            "aggregated_query_unit_ids": aggregated_query_unit_ids,
        }

    async def _synthesize(
        self,
        task: Task,
        query: str,
        materials: list[dict[str, str]],
    ) -> dict[str, Any]:
        if not materials:
            raise ValueError(f"no materials for task {task.id}")

        prompt = self._build_prompt(task, query, materials)
        try:
            raw = await self.client.generate(
                prompt=prompt,
                system_prompt=_SYSTEM_PROMPT,
            )
            markdown = raw.strip()
        except Exception:
            markdown = self._fallback_synthesize(task, query, materials)
        if not markdown:
            markdown = self._fallback_synthesize(task, query, materials)
        return {
            "task_id": task.id,
            "markdown": markdown,
        }

    def _build_prompt(
        self,
        task: Task,
        query: str,
        materials: list[dict[str, str]],
    ) -> str:
        title = task.description.strip() or task.id
        material_sections = []
        for mat in materials:
            material_sections.append(
                f"--- source: {mat['source']} ---\n{mat['content']}"
            )
        materials_text = "\n\n".join(material_sections)

        instruction = ""
        if task.merge_instruction.strip():
            instruction = f"\n[INSTRUCTION]\n{task.merge_instruction.strip()}\n"

        return (
            "당신은 정량적 금융 분석가입니다.\n"
            "아래 자료를 빠짐없이 활용하여 종합 보고서 섹션을 작성하십시오.\n\n"
            f"[TASK]\n{title}\n\n"
            f"[QUERY]\n{query}\n"
            f"{instruction}\n"
            f"[MATERIALS]\n{materials_text}\n\n"
            "규칙:\n"
            "- 한글 마크다운으로 작성.\n"
            "- 모든 정량적 데이터, 수치, 팩트를 빠짐없이 보존.\n"
            "- Quant 관점으로 재해석하되, 원본 정보를 생략하지 않음.\n"
            "- 명확한 헤더와 구조로 작성.\n"
            "- 마크다운 텍스트만 반환 (JSON 래핑 없이)."
        )

    async def _compose_final_report(
        self,
        query: str,
        analysis_strategy: str,
        root_markdown: str,
    ) -> str:
        today = date.today().isoformat()

        strategy_section = ""
        if analysis_strategy.strip():
            strategy_section = f"[ANALYSIS STRATEGY]\n{analysis_strategy}\n\n"

        rules = [
            "- 분석 전략의 모든 차원을 다루십시오.",
            "- 수집된 데이터의 모든 정량적 수치를 보존하십시오.",
            "- 수집 리서치에 없는 정보를 지어내지 마십시오.",
            f"- 보고서 날짜: {today}",
            "- 한글 마크다운. 마크다운 텍스트만 반환.",
        ]
        rules_text = "\n".join(rules)

        prompt = (
            "당신은 비판적 시니어 equity research 애널리스트입니다.\n"
            "아래 분석 전략과 종합 리서치를 바탕으로 최종 투자 보고서를 작성하십시오.\n\n"
            f"[QUERY]\n{query}\n\n"
            f"{strategy_section}"
            f"[TODAY]\n{today}\n\n"
            f"[RESEARCH]\n{root_markdown}\n\n"
            "원칙:\n"
            f"{rules_text}"
        )
        try:
            raw = await self.client.generate(
                prompt=prompt,
                system_prompt=_SYSTEM_PROMPT,
            )
            markdown = raw.strip()
            if markdown:
                return markdown
        except Exception:
            pass
        return self._fallback_final_report(
            query,
            analysis_strategy,
            root_markdown,
            today,
        )

    def _fallback_synthesize(
        self,
        task: Task,
        query: str,
        materials: list[dict[str, str]],
    ) -> str:
        title = task.description.strip() or task.id
        lines = [f"# {title}", "", f"- query: {query}", ""]
        for item in materials:
            source = item.get("source", "unknown")
            content = item.get("content", "").strip()
            if len(content) > 800:
                content = content[:800] + "..."
            lines.append(f"## source: {source}")
            lines.append(content or "(empty)")
            lines.append("")
        return "\n".join(lines).strip()

    def _fallback_final_report(
        self,
        query: str,
        analysis_strategy: str,
        root_markdown: str,
        today: str,
    ) -> str:
        strategy = analysis_strategy.strip() or "N/A"
        return (
            f"# Final Report\n\n"
            f"- date: {today}\n"
            f"- query: {query}\n\n"
            f"## Analysis Strategy\n{strategy}\n\n"
            f"## Aggregated Research\n{root_markdown.strip()}\n"
        )
