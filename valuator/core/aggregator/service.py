from __future__ import annotations

from typing import Any, Awaitable, Callable

from ...models.gemini_direct import GeminiClient
from ...utils.config import config
from ..contracts.plan import Plan, Task
from ..contracts.requirement import evaluate_contract
from ..workspace.service import Workspace
from .graph_ops import descendant_leaf_task_ids, infer_root_task_id, post_order_tasks
from .materials import (
    collect_materials,
    extract_leaf_artifacts,
    query_unit_ids_for_leaf_tasks,
)

_SYSTEM_PROMPT = "한글 마크다운 보고서만 반환하십시오."


class Aggregation:
    def __init__(self, client: GeminiClient | None = None):
        self.client = client or GeminiClient(config.agent_model)

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.client.bind_usage_writer(usage_writer)

    async def aggregate(
        self,
        query: str,
        plan: Plan,
        execution: dict,
        workspace: Workspace,
        on_task_aggregated: Callable[[Task, int, int], Awaitable[None]] | None = None,
    ) -> dict:
        leaf_artifacts = extract_leaf_artifacts(execution)
        task_map = {task.id: task for task in plan.tasks}
        descendant_cache: dict[str, list[dict[str, str]]] = {}
        reports: dict[str, dict[str, Any]] = {}

        task_order = post_order_tasks(plan)
        total_tasks = len(task_order)
        for index, task_id in enumerate(task_order, start=1):
            task = task_map[task_id]
            materials = collect_materials(
                task,
                task_map,
                leaf_artifacts,
                reports,
                descendant_cache,
            )
            if task.task_type == "leaf":
                report = self._leaf_passthrough(task=task, materials=materials)
            else:
                contract_section, contract_markers = self._contract_section(plan, task_id)
                report = await self._synthesize(
                    task=task,
                    query=query,
                    materials=materials,
                    contract_section=contract_section,
                    contract_markers=contract_markers,
                )
            reports[task_id] = report
            workspace.write_output(
                f"/aggregation/{task_id}/report.md",
                report["markdown"],
            )
            if on_task_aggregated is not None:
                await on_task_aggregated(task, index, total_tasks)

        root_task_id = plan.root_task_id or infer_root_task_id(plan.tasks)
        root_report = reports.get(root_task_id)
        if not root_report:
            raise ValueError(f"root node report is missing: {root_task_id}")

        descendant_leaf_ids = descendant_leaf_task_ids(root_task_id, task_map)
        aggregated_leaf_task_ids = sorted(
            task_id for task_id in descendant_leaf_ids if leaf_artifacts.get(task_id)
        )
        aggregated_query_unit_ids = query_unit_ids_for_leaf_tasks(
            aggregated_leaf_task_ids, task_map
        )

        final_md = root_report["markdown"]
        missing_contract_items = evaluate_contract(plan.contract, final_md)
        return {
            "final_markdown": final_md,
            "root_task_id": root_task_id,
            "aggregated_leaf_task_ids": aggregated_leaf_task_ids,
            "aggregated_query_unit_ids": aggregated_query_unit_ids,
            "final_included_leaf_task_ids": aggregated_leaf_task_ids,
            "final_included_query_unit_ids": aggregated_query_unit_ids,
            "missing_contract_items": missing_contract_items,
        }

    def _leaf_passthrough(
        self,
        *,
        task: Task,
        materials: list[dict[str, str]],
    ) -> dict[str, Any]:
        lines: list[str] = [f"# {task.description.strip() or task.id}", ""]
        if not materials:
            lines.append("- no leaf artifacts")
        else:
            for mat in materials:
                lines.append(f"## source: {mat.get('source', 'unknown')}")
                lines.append((mat.get("content", "") or "").strip() or "(empty)")
                lines.append("")
        return {"task_id": task.id, "markdown": "\n".join(lines).strip()}

    async def _synthesize(
        self,
        task: Task,
        query: str,
        materials: list[dict[str, str]],
        contract_section: str,
        contract_markers: list[str],
    ) -> dict[str, Any]:
        if not materials:
            raise ValueError(f"no materials for task {task.id}")

        prompt = self._build_prompt(task, query, materials, contract_section)
        markdown = ""
        try:
            raw = await self.client.generate(
                prompt=prompt,
                system_prompt=_SYSTEM_PROMPT,
                trace_method="aggregator._synthesize",
            )
            markdown = raw.strip()
        except Exception:
            pass
        if not markdown:
            markdown = self._fallback_synthesize(
                task, query, materials, contract_markers
            )
        return {
            "task_id": task.id,
            "markdown": markdown,
        }

    def _build_prompt(
        self,
        task: Task,
        query: str,
        materials: list[dict[str, str]],
        contract_section: str,
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
        contract_text = ""
        if contract_section.strip():
            contract_text = f"\n[CONTRACT]\n{contract_section}\n"

        return (
            "당신은 정량적 금융 분석가입니다.\n"
            "아래 계약과 자료를 빠짐없이 활용하여 종합 보고서 섹션을 작성하십시오.\n\n"
            f"[TASK]\n{title}\n\n"
            f"[QUERY]\n{query}\n"
            f"{instruction}\n"
            f"{contract_text}\n"
            f"[MATERIALS]\n{materials_text}\n\n"
            "규칙:\n"
            "- 한글 마크다운으로 작성.\n"
            "- 모든 정량적 데이터, 수치, 팩트를 빠짐없이 보존.\n"
            "- Quant 관점으로 재해석하되, 원본 정보를 생략하지 않음.\n"
            "- 시점은 반드시 절대 표현으로 작성 (예: 2025Q3, 2026-01-08).\n"
            "- 상대 시점 표현(최근, 향후, 단기, 장기, 작년, 내년)을 사용하지 않음.\n"
            "- 리스크는 존재 여부만 쓰지 말고 손익/현금흐름 전이 경로로 설명.\n"
            "- 명확한 헤더와 구조로 작성.\n"
            "- 자료에 valuation/pricing 좌표(시총, PER, PBR, 가격대, 목표가)가 있으면 누락 없이 유지.\n"
            "- 투자 액션/트리거는 반드시 수치 임계치를 포함.\n"
            "- QUERY/CONTRACT에 명시된 핵심 기업/티커는 유지하고, 다른 종목/테마로 대체하지 않음.\n"
            "- [CONTRACT] 섹션이 있으면 각 항목마다 `## [R-xxx]` 헤더를 반드시 하나씩 포함.\n"
            "- 각 `## [R-xxx]` 섹션은 해당 requirement를 직접 충족하는 답변을 포함.\n"
            "- 마크다운 텍스트만 반환 (JSON 래핑 없이)."
        )

    def _contract_section(self, plan: Plan, task_id: str) -> tuple[str, list[str]]:
        if plan.contract is None:
            return "", []
        if plan.root_task_id and task_id != plan.root_task_id:
            return "", []

        lines: list[str] = []
        markers: list[str] = []
        for item in plan.contract.items:
            lines.append(
                f"- [{item.id}] unit={item.unit_id} required={item.required} requirement={item.acceptance}"
            )
            markers.append(item.id)
        if not lines:
            return "", []
        return "\n".join(lines), markers

    def _fallback_synthesize(
        self,
        task: Task,
        query: str,
        materials: list[dict[str, str]],
        contract_markers: list[str],
    ) -> str:
        title = task.description.strip() or task.id
        lines = [f"# {title}", "", f"- query: {query}", ""]
        if contract_markers:
            lines.append("## Contract Coverage")
            lines.append("")
            for marker in contract_markers:
                lines.append(f"## [{marker}]")
                lines.append("- requirement: covered in fallback output")
                lines.append("")
        for item in materials:
            source = item.get("source", "unknown")
            content = item.get("content", "").strip()
            lines.append(f"## source: {source}")
            lines.append(content or "(empty)")
            lines.append("")
        return "\n".join(lines).strip()
