from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable

from ...domain import DomainModuleContext
from ...models.gemini_direct import GeminiClient
from ...utils.config import config
from ..contracts.plan import (
    AggregationResult,
    DomainCoverage,
    ExecutionArtifact,
    ExecutionResult,
    Plan,
    ReportMaterial,
    Task,
    TaskReport,
    evaluate_contract,
    parse_contract_coverage,
)
from ..workspace.service import Workspace
from .graph_ops import descendant_leaf_task_ids, post_order_tasks
from .materials import (
    collect_domain_artifacts,
    collect_materials,
    extract_artifacts_by_task,
    extract_leaf_artifacts,
    query_unit_ids_for_leaf_tasks,
)

_SYSTEM_PROMPT = "한글 마크다운 보고서만 반환하십시오."
_DIRECT_NUMERIC_DISCREPANCY_MARKERS = (
    "단위 불일치",
    "unit mismatch",
    "unit discrepancy",
)
_SCALE_SENSITIVE_ROW_TOKENS = (
    "매출",
    "revenue",
    "자산",
    "assets",
    "부채",
    "liabilities",
    "자본",
    "equity",
    "현금흐름",
    "cash flow",
)


class Aggregation:
    def __init__(self, client: GeminiClient | None = None):
        self.client = client or GeminiClient(config.agent_model)
        self._domain_context: DomainModuleContext | None = None

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.client.bind_usage_writer(usage_writer)

    def bind_domain_context(
        self,
        domain_context: DomainModuleContext | None,
    ) -> None:
        self._domain_context = domain_context

    async def aggregate(
        self,
        query: str,
        plan: Plan,
        execution: ExecutionResult,
        workspace: Workspace,
        on_task_aggregated: Callable[[Task, int, int], Awaitable[None]] | None = None,
    ) -> AggregationResult:
        leaf_artifacts = extract_leaf_artifacts(execution.artifacts)
        artifact_index = extract_artifacts_by_task(execution.artifacts)
        task_map = {task.id: task for task in plan.tasks}
        reports: dict[str, TaskReport] = {}

        task_order = post_order_tasks(plan)
        total_tasks = len(task_order)
        for index, task_id in enumerate(task_order, start=1):
            report = await self.build_task_report(
                query=query,
                plan=plan,
                task_id=task_id,
                task_map=task_map,
                artifact_materials=leaf_artifacts,
                artifact_index=artifact_index,
                reports=reports,
            )
            reports[task_id] = report
            workspace.write_aggregation_report(task_id, report.markdown)
            if on_task_aggregated is not None:
                await on_task_aggregated(task_map[task_id], index, total_tasks)

        return self.finalize_aggregation(
            plan=plan,
            task_map=task_map,
            artifact_materials=leaf_artifacts,
            artifact_index=artifact_index,
            reports=reports,
        )

    async def build_task_report(
        self,
        *,
        query: str,
        plan: Plan,
        task_id: str,
        task_map: dict[str, Task],
        artifact_materials: dict[str, list[ReportMaterial]],
        artifact_index: dict[str, list[ExecutionArtifact]],
        reports: dict[str, TaskReport],
    ) -> TaskReport:
        task = task_map[task_id]
        materials = collect_materials(
            task,
            task_map,
            artifact_materials,
            reports,
            {},
        )
        domain_artifacts = collect_domain_artifacts(
            task,
            task_map,
            artifact_index,
        )
        if task.task_type != "merge":
            return self._leaf_passthrough(task=task, materials=materials)

        contract_section = self._contract_section(plan, task_id)
        scoped_domain_ids = self._task_domain_ids(plan=plan, task=task)
        report = await self._synthesize(
            task=task,
            is_root=task.id == (plan.root_task_id or ""),
            query=query,
            materials=materials,
            domain_artifacts=domain_artifacts,
            scoped_domain_ids=scoped_domain_ids,
            contract_section=contract_section,
        )
        return report

    def finalize_aggregation(
        self,
        *,
        plan: Plan,
        task_map: dict[str, Task],
        artifact_materials: dict[str, list[ReportMaterial]],
        artifact_index: dict[str, list[ExecutionArtifact]],
        reports: dict[str, TaskReport],
    ) -> AggregationResult:
        root_task_id = plan.root_task_id
        root_report = reports.get(root_task_id)
        if not root_report:
            raise ValueError(f"root node report is missing: {root_task_id}")

        descendant_leaf_ids = descendant_leaf_task_ids(root_task_id, task_map)
        aggregated_leaf_task_ids = sorted(
            task_id
            for task_id in descendant_leaf_ids
            if task_map[task_id].task_type == "leaf" and artifact_materials.get(task_id)
        )
        aggregated_query_unit_ids = query_unit_ids_for_leaf_tasks(
            aggregated_leaf_task_ids, task_map
        )

        final_md = root_report.markdown
        covered_contract_item_ids = parse_contract_coverage(final_md)
        missing_contract_items = evaluate_contract(
            plan.analysis.requirements,
            final_md,
            covered_item_ids=covered_contract_item_ids,
        )
        covered_query_unit_ids = sorted(
            {
                unit_id
                for item in plan.analysis.requirements
                if item.id in covered_contract_item_ids
                for unit_id in item.unit_ids
            }
        )
        root_domain_artifacts = collect_domain_artifacts(
            task_map[root_task_id],
            task_map,
            artifact_index,
        )
        domain_coverage = self._domain_coverage_summary(
            final_markdown=final_md,
            domain_artifacts=root_domain_artifacts,
        )
        aggregation_error = self._detect_aggregation_error(final_md)
        return AggregationResult(
            final_markdown=final_md,
            root_task_id=root_task_id or "",
            aggregated_query_unit_ids=aggregated_query_unit_ids,
            final_included_query_unit_ids=(
                covered_query_unit_ids
                if covered_query_unit_ids
                else aggregated_query_unit_ids
            ),
            missing_requirement_ids=missing_contract_items,
            covered_requirement_ids=covered_contract_item_ids,
            domain_coverage=domain_coverage,
            aggregation_error=aggregation_error,
        )

    def _leaf_passthrough(
        self,
        *,
        task: Task,
        materials: list[ReportMaterial],
    ) -> TaskReport:
        lines: list[str] = [f"# {task.description.strip() or task.id}", ""]
        if not materials:
            lines.append("- no leaf artifacts")
        else:
            for mat in materials:
                lines.append(f"## source: {mat.source}")
                lines.append(mat.content.strip() or "(empty)")
                if mat.facts:
                    lines.append("")
                    lines.append("### key-value facts")
                    for key, value in mat.facts.items():
                        lines.append(f"- {key}: {value}")
                lines.append("")
        return TaskReport(task_id=task.id, markdown="\n".join(lines).strip())

    async def _synthesize(
        self,
        task: Task,
        is_root: bool,
        query: str,
        materials: list[ReportMaterial],
        domain_artifacts: list[ExecutionArtifact],
        scoped_domain_ids: list[str],
        contract_section: str,
    ) -> TaskReport:
        if not materials:
            raise ValueError(f"no materials for task {task.id}")

        prompt = self._build_prompt(
            task,
            is_root,
            query,
            materials,
            domain_artifacts,
            scoped_domain_ids,
            contract_section,
        )
        raw = await self.client.generate(
            prompt=prompt,
            system_prompt=_SYSTEM_PROMPT,
            trace_method="aggregator._synthesize",
        )
        markdown = raw.strip()
        if not markdown:
            raise ValueError(f"empty synthesis output: {task.id}")
        return TaskReport(task_id=task.id, markdown=markdown)

    def _build_prompt(
        self,
        task: Task,
        is_root: bool,
        query: str,
        materials: list[ReportMaterial],
        domain_artifacts: list[ExecutionArtifact],
        scoped_domain_ids: list[str],
        contract_section: str,
    ) -> str:
        title = task.description.strip() or task.id
        material_sections = []
        for mat in materials:
            block = f"--- source: {mat.source} ---\n{mat.content}"
            if mat.facts:
                fact_lines = "\n".join(
                    f"- {key}: {value}" for key, value in mat.facts.items()
                )
                block += f"\n[KEY_VALUE_FACTS]\n{fact_lines}"
            material_sections.append(block)
        materials_text = "\n\n".join(material_sections)

        instruction = ""
        if task.merge_instruction.strip():
            instruction = f"\n[INSTRUCTION]\n{task.merge_instruction.strip()}\n"
        contract_text = ""
        if contract_section.strip():
            contract_text = f"\n[CONTRACT]\n{contract_section}\n"
        domain_guidance = self._domain_guidance_section(scoped_domain_ids)
        guidance_text = ""
        if domain_guidance:
            guidance_text = f"\n[DOMAIN_GUIDANCE]\n{domain_guidance}\n"
        overview_text, detail_text = self._domain_evidence_sections(
            domain_artifacts,
            scoped_domain_ids,
        )
        domain_overview_text = ""
        if overview_text:
            domain_overview_text = f"\n[DOMAIN_EVIDENCE_OVERVIEW]\n{overview_text}\n"
        domain_detail_text = ""
        if detail_text:
            domain_detail_text = f"\n[DOMAIN_EVIDENCE_DETAILS]\n{detail_text}\n"
        scoped_domain_text = ", ".join(scoped_domain_ids) or "(none)"
        prompt = (
            "당신은 정량적 금융 분석가입니다.\n"
            "아래 계약과 자료를 빠짐없이 활용하여 보고서 마크다운을 작성하십시오.\n\n"
            f"[TASK]\n{title}\n\n"
            f"[QUERY]\n{query}\n"
            f"[SCOPED_DOMAINS]\n{scoped_domain_text}\n"
            f"{instruction}\n"
            f"{contract_text}\n"
            f"{guidance_text}\n"
            f"{domain_overview_text}\n"
            f"{domain_detail_text}\n"
            f"[MATERIALS]\n{materials_text}\n\n"
        )
        if is_root:
            intent_text = self._intent_guidance_text()
            if intent_text:
                prompt += f"[INTENT_GUIDANCE]\n{intent_text}\n\n"
            prompt += (
                "규칙:\n"
                "- 한글 마크다운으로 작성.\n"
                "- 모든 정량적 데이터, 수치, 팩트를 빠짐없이 보존.\n"
                "- 먼저 `## 개괄` 섹션에서 핵심 결론/핵심 가정/핵심 리스크를 요약.\n"
                "- 이후 `## 도메인 상세` 섹션에서 현재 TASK에 실제로 관련된 도메인만 상세히 작성.\n"
                "- 도메인 상세 헤더는 `### [DOMAIN:<module_id>] <module_name>` 형식을 사용. `<module_id>`는 반드시 `[SCOPED_DOMAINS]`에 나온 id만 사용.\n"
                "- 도메인 모듈에 해당하지 않는 내용은 `### [SECTION:제목]` 형태로 작성한다.\n"
                "- `DOMAIN_EVIDENCE_OVERVIEW`와 `KEY_VALUE_FACTS`를 우선 사용해 key:value를 본문에 명시한다.\n"
                "- Quant 관점으로 재해석하되, 원본 정보와 key:value를 생략하지 않는다.\n"
                "- 시점은 반드시 절대 표현으로 작성한다 (예: 2025Q3, 2026-01-08).\n"
                "- 상대 시점 표현(최근, 향후, 단기, 장기, 작년, 내년)을 사용하지 않는다.\n"
                "- 리스크는 존재 여부만 쓰지 말고 손익/현금흐름 전이 경로로 설명한다.\n"
                "- 자료에 valuation/pricing 좌표(시총, PER, PBR, 가격대, 목표가)가 있으면 누락 없이 유지한다.\n"
                "- 투자 액션/트리거는 반드시 수치 임계치를 포함한다.\n"
                "- QUERY/CONTRACT에 명시된 핵심 기업/티커, 추천 형식, 비교 형식, 시장 제약을 유지하고 다른 종목/테마로 대체하지 않는다.\n"
                "- [CONTRACT]가 있으면 requirement를 모두 충족하되, 중복 문장/중복 섹션은 만들지 않는다.\n"
                "- 문서 마지막에 `[CONTRACT_COVERAGE]` 한 줄을 추가하고, [CONTRACT_IDS]에 있는 항목 중 본문에서 충족한 모든 requirement id를 쉼표로 빠짐없이 나열한다.\n"
                "- 마크다운 텍스트만 반환한다 (JSON 래핑 없이).\n"
            )
            return prompt

        return (
            prompt
            + "규칙:\n"
            + "- 이것은 최종 보고서가 아니라 현재 TASK 전용 중간 합성본이다.\n"
            + "- `[SCOPED_DOMAINS]` 밖의 도메인, 일반 시장 서론, unrelated macro narrative를 추가하지 않는다.\n"
            + "- 모든 정량 데이터, 종목명, 티커, 가격 좌표, 출처 단서를 빠짐없이 유지한다.\n"
            + "- `### [DOMAIN:<module_id>] <module_name>` 형식은 `[SCOPED_DOMAINS]`에 포함된 도메인에만 사용한다.\n"
            + "- 비도메인 내용은 `### [SECTION:제목]`으로 작성한다.\n"
            + "- 최종 리포트용 전역 scaffold(`## 개괄`, `## 도메인 상세`, `[CONTRACT_COVERAGE]`)는 사용하지 않는다.\n"
            + "- QUERY가 추천/비교/스크리닝이면 그 행위를 유지한 sub-report를 작성하고 generic investment report로 바꾸지 않는다.\n"
            + "- 마크다운 텍스트만 반환한다 (JSON 래핑 없이).\n"
        )

    def _contract_section(self, plan: Plan, task_id: str) -> str:
        lines: list[str] = []
        task_map = {task.id: task for task in plan.tasks}
        task = task_map[task_id]
        relevant_unit_ids = sorted(set(task.query_unit_ids))
        if relevant_unit_ids:
            lines.append("[QUERY_UNITS]")
            for unit_id in relevant_unit_ids:
                unit = plan.analysis.units[unit_id]
                lines.append(
                    f"- unit_id={unit_id} id={unit.id} objective={unit.objective}"
                )
                lines.append(f"  - retrieval_query={unit.retrieval_query}")
                if unit.domain_ids:
                    lines.append(f"  - domain_ids={', '.join(unit.domain_ids)}")
                if unit.entity_ids:
                    lines.append(f"  - entity_ids={', '.join(unit.entity_ids)}")
                if unit.time_scope.strip():
                    lines.append(f"  - time_scope={unit.time_scope.strip()}")

        relevant_items = [
            item
            for item in plan.analysis.requirements
            if set(item.unit_ids).intersection(relevant_unit_ids)
        ]
        required_ids = [item.id for item in relevant_items if item.required]
        if required_ids:
            lines.append("[CONTRACT_IDS] " + ", ".join(required_ids))
        if relevant_items:
            lines.append("[REQUIREMENTS]")
            for item in relevant_items:
                lines.append(
                    f"- [{item.id}] units={item.unit_ids} domains={item.domain_ids} "
                    f"entities={item.entity_ids} required={item.required} acceptance={item.acceptance}"
                )

        base = "\n".join(lines) if lines else ""
        domain_section = self._domain_contract_section(self._task_domain_ids(plan=plan, task=task))
        if base and domain_section:
            return base + "\n" + domain_section
        if domain_section:
            return domain_section
        return base

    def _domain_contract_section(self, module_ids: list[str]) -> str:
        ctx = self._domain_context
        if ctx is None or not module_ids:
            return ""

        lines: list[str] = []
        lines.append("[DOMAIN_REPORT_CONTRACT]")
        for module_id in module_ids:
            module = ctx.modules.get(module_id)
            if module is None:
                continue
            lines.append(f"- module={module.id} name={module.name}")
            for req in module.report_contract:
                text = req.text
                if not text:
                    continue
                lines.append(f"  - {text}")
        return "\n".join(lines) if len(lines) > 1 else ""

    def _domain_guidance_section(self, module_ids: list[str]) -> str:
        ctx = self._domain_context
        if ctx is None or not module_ids:
            return ""

        lines: list[str] = []
        for module_id in module_ids:
            module = ctx.modules.get(module_id)
            if module is None:
                continue
            lines.append(f"- module={module.id} name={module.name}")
            fragment = module.prompt_fragment.strip()
            if not fragment:
                continue
            lines.append(f"  - guidance={fragment}")
        return "\n".join(lines)

    def _domain_evidence_sections(
        self,
        domain_artifacts: list[ExecutionArtifact],
        module_ids: list[str],
    ) -> tuple[str, str]:
        grouped: dict[str, list[ExecutionArtifact]] = {}
        for artifact in domain_artifacts:
            grouped.setdefault(artifact.domain_id, []).append(artifact)

        ordered_ids: list[str] = []
        ctx = self._domain_context
        if module_ids:
            ordered_ids.extend(module_ids)
        for module_id in grouped:
            if module_id not in ordered_ids:
                ordered_ids.append(module_id)

        if not ordered_ids:
            return "", ""

        overview_lines: list[str] = []
        detail_lines: list[str] = []
        for module_id in ordered_ids:
            module_artifacts = grouped.get(module_id, [])
            module_name = module_id
            if ctx is not None:
                module = ctx.modules.get(module_id)
                if module is not None:
                    module_name = module.name

            if not module_artifacts:
                overview_lines.append(
                    f"- module={module_id} name={module_name} evidence=none"
                )
                detail_lines.append(
                    f"### module={module_id} name={module_name}\n- evidence: none"
                )
                continue

            merged_key_values: dict[str, str] = {}
            summaries: list[str] = []
            for artifact in module_artifacts:
                merged_key_values.update(artifact.domain_key_values)
                summary = artifact.domain_summary.strip()
                if summary and summary not in summaries:
                    summaries.append(summary)

            summary_text = "; ".join(summaries) if summaries else "N/A"
            overview_lines.append(f"- module={module_id} name={module_name}")
            overview_lines.append(f"  - summary={summary_text}")
            if merged_key_values:
                for key, value in merged_key_values.items():
                    overview_lines.append(f"  - {key}={value}")

            detail_lines.append(f"### module={module_id} name={module_name}")
            for idx, artifact in enumerate(module_artifacts, start=1):
                detail_lines.append(
                    f"- evidence#{idx}.summary: {artifact.domain_summary or 'N/A'}"
                )
                if artifact.domain_key_values:
                    detail_lines.append("  - key_values:")
                    for key, value in artifact.domain_key_values.items():
                        detail_lines.append(f"    - {key}: {value}")
                if artifact.domain_payload:
                    detail_lines.append("  - payload_json:")
                    detail_lines.append("```json")
                    payload_str = json.dumps(
                        artifact.domain_payload, ensure_ascii=False, indent=2, default=str
                    )
                    detail_lines.append(payload_str)
                    detail_lines.append("```")

        return "\n".join(overview_lines), "\n".join(detail_lines)

    def _task_domain_ids(self, *, plan: Plan, task: Task) -> list[str]:
        scoped: list[str] = []
        ctx = self._domain_context
        active_ids = (
            [
                module_id
                for module_id in ctx.module_ids
                if module_id in ctx.modules
            ]
            if ctx is not None and ctx.module_ids
            else []
        )

        if task.domain_id.strip():
            scoped.append(task.domain_id.strip())
        for unit_id in task.query_unit_ids:
            if unit_id < 0 or unit_id >= len(plan.query_units):
                continue
            for domain_id in plan.query_units[unit_id].domain_ids:
                if domain_id not in scoped:
                    scoped.append(domain_id)

        if active_ids:
            ordered = [module_id for module_id in active_ids if module_id in scoped]
            if ordered:
                return ordered
            if task.id == (plan.root_task_id or ""):
                return active_ids
        return scoped

    def _intent_guidance_text(self) -> str:
        ctx = self._domain_context
        if ctx is None or ctx.query_analysis is None:
            return ""
        tags = [tag.strip().lower() for tag in ctx.query_analysis.intent_tags if tag.strip()]
        if not tags:
            return ""
        lines = [f"- intent_tags={', '.join(tags)}"]
        if "recommendation" in tags or "screening" in tags:
            lines.append(
                "- recommendation/screening query: final answer must contain explicit candidate picks or shortlist output, direct selection logic, and when-not-to-buy conditions."
            )
        if "comparison" in tags:
            lines.append(
                "- comparison query: preserve side-by-side comparison framing instead of collapsing to a generic narrative."
            )
        if "single_subject" not in tags:
            lines.append(
                "- no single concrete issuer: do not fabricate a placeholder company subject."
            )
        return "\n".join(lines)

    def _domain_coverage_summary(
        self,
        *,
        final_markdown: str,
        domain_artifacts: list[ExecutionArtifact],
    ) -> DomainCoverage:
        ctx = self._domain_context
        active_ids: list[str] = []
        if ctx is not None and ctx.module_ids:
            active_ids = list(ctx.module_ids)
        else:
            active_ids = sorted(
                {artifact.domain_id for artifact in domain_artifacts if artifact.domain_id}
            )

        evidence_ids = sorted(
            {artifact.domain_id for artifact in domain_artifacts if artifact.domain_id}
        )
        final_ids: list[str] = []
        for module_id in active_ids:
            marker = f"[DOMAIN:{module_id}]"
            if marker in final_markdown:
                final_ids.append(module_id)

        return DomainCoverage(
            final_ids=final_ids,
            evidence_ids=evidence_ids,
        )

    def _detect_aggregation_error(self, final_markdown: str) -> str:
        lowered = final_markdown.lower()
        for marker in _DIRECT_NUMERIC_DISCREPANCY_MARKERS:
            if marker in lowered:
                return "final markdown reports a unit mismatch in its own numeric evidence"

        for table in self._table_blocks(final_markdown):
            issue = self._table_scale_issue(table)
            if issue:
                return issue
        return ""

    def _table_blocks(self, markdown: str) -> list[list[str]]:
        blocks: list[list[str]] = []
        current: list[str] = []
        for raw_line in markdown.splitlines():
            line = raw_line.strip()
            if "|" not in line:
                if current:
                    blocks.append(current)
                    current = []
                continue
            current.append(line)
        if current:
            blocks.append(current)
        return blocks

    def _table_scale_issue(self, lines: list[str]) -> str:
        for line in lines:
            if ":---" in line or "---" == line.replace("|", "").replace(":", "").strip():
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) < 3:
                continue
            label = cells[0].lower()
            if not any(token in label for token in _SCALE_SENSITIVE_ROW_TOKENS):
                continue
            values = [self._numeric_cell_value(cell) for cell in cells[1:]]
            issue = self._scale_jump_issue(label, values)
            if issue:
                return issue
        return ""

    def _scale_jump_issue(self, label: str, values: list[float | None]) -> str:
        previous: float | None = None
        for value in values:
            if value is None or value <= 0:
                previous = value
                continue
            if previous is not None and previous > 0:
                larger = max(previous, value)
                smaller = min(previous, value)
                if smaller >= 10000 and larger / smaller >= 8:
                    return f"final markdown contains a likely unit-scale mismatch in row '{label}'"
            previous = value
        return ""

    def _numeric_cell_value(self, cell: str) -> float | None:
        match = re.search(r"-?\d[\d,]*\.?\d*", cell)
        if match is None:
            return None
        return float(match.group(0).replace(",", ""))
