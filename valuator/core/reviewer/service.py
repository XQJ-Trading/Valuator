"""Reviewer service: single review call over query spec, layer state, and final markdown."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from ...domain import (
    DomainModuleContext,
    QueryRequirement,
    build_query_breakdown,
)
from ...models.gemini_direct import GeminiClient
from ...utils.config import config
from ..contracts.plan import (
    AggregationResult,
    ExecutionResult,
    Plan,
    ReviewResult,
    Task,
)
from .prompts import (
    REVIEWER_SYSTEM,
    build_reviewer_response_json_schema,
    build_reviewer_user_prompt,
)


class Reviewer:
    def __init__(self, client: GeminiClient | None = None) -> None:
        self.client = client or GeminiClient(config.agent_model)
        self._now_utc_iso: str | None = None
        self._domain_context: DomainModuleContext | None = None

    def bind_now_utc(self, now_utc: datetime) -> None:
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        self._now_utc_iso = (
            now_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        )

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.client.bind_usage_writer(usage_writer)

    def bind_domain_context(
        self,
        domain_context: DomainModuleContext | None,
    ) -> None:
        self._domain_context = domain_context

    async def review(
        self,
        plan: Plan,
        execution: ExecutionResult,
        aggregation: AggregationResult,
    ) -> ReviewResult:
        now_utc = self._now_utc_iso or self._current_now_utc_iso()
        unit_count = len(plan.analysis.units)
        final_markdown = aggregation.final_markdown
        final_empty = not final_markdown.strip()
        leaf_tasks = {task.id: task for task in plan.tasks if task.task_type == "leaf"}
        completed_leaf_ids = set(execution.completed_leaf_task_ids)
        missing_leaf_task_ids = sorted(set(leaf_tasks) - completed_leaf_ids)
        mapped_units = {
            unit_id for task in leaf_tasks.values() for unit_id in task.query_unit_ids
        }
        units_without_leaf_mapping = [
            unit_id for unit_id in range(unit_count) if unit_id not in mapped_units
        ]

        plan_layer = self._plan_layer(plan)
        execution_layer = self._execution_layer(plan, completed_leaf_ids)
        aggregation_layer = self._aggregation_layer(plan, aggregation)
        candidate_nodes = self._structural_candidate_nodes(
            unit_count=unit_count,
            missing_leaf_task_ids=missing_leaf_task_ids,
            leaf_tasks=leaf_tasks,
            units_without_leaf_mapping=units_without_leaf_mapping,
            final_empty=final_empty,
        )
        requirement_ids = [item.id for item in plan.analysis.requirements]
        active_domain_ids = self._active_domain_ids(plan)
        diagnostics = {
            "missing_leaf_task_ids": missing_leaf_task_ids,
            "units_without_leaf_mapping": units_without_leaf_mapping,
            "aggregation_error": aggregation.aggregation_error.strip(),
        }
        query_spec = self._query_spec_blob(plan)
        user_prompt = build_reviewer_user_prompt(
            query=plan.query,
            query_spec=query_spec,
            plan_layer=plan_layer,
            execution_layer=execution_layer,
            aggregation_layer=aggregation_layer,
            candidate_actions=[{"node": node} for node in candidate_nodes],
            final_markdown=final_markdown,
            now_utc=now_utc,
            diagnostics=diagnostics,
        )
        response_schema = build_reviewer_response_json_schema(
            max_node=max(unit_count - 1, 0),
            requirement_ids=requirement_ids,
            domain_ids=active_domain_ids,
        )
        data = await self.client.generate_json(
            prompt=user_prompt,
            system_prompt=REVIEWER_SYSTEM,
            response_json_schema=response_schema,
            trace_method="reviewer.review",
        )

        missing_requirement_ids = list(data["missing_requirement_ids"])
        missing_final_domain_ids = list(data["missing_final_domain_ids"])
        actions = self._collapse_actions(data["actions"], unit_count)
        self_assessment = data["self_assessment"]
        quant_axes = data["quant_axes"]
        semantic_below_axes = self._semantic_below_axes(quant_axes)

        query_signals = self._query_signals(
            requirements=plan.analysis.requirements,
            missing_requirement_ids=missing_requirement_ids,
        )
        unit_signals = self._unit_signals(
            unit_count=unit_count,
            completed_leaf_ids=completed_leaf_ids,
            leaf_tasks=leaf_tasks,
            aggregated_query_unit_ids=aggregation.aggregated_query_unit_ids,
            final_included_query_unit_ids=aggregation.final_included_query_unit_ids,
            missing_requirement_ids=missing_requirement_ids,
            requirements=plan.analysis.requirements,
            final_empty=final_empty,
        )
        domain_signals = self._domain_signals(
            plan=plan,
            aggregation=aggregation,
            missing_final_domain_ids=missing_final_domain_ids,
        )

        signals = {
            "query": query_signals,
            "units": unit_signals,
            "domains": domain_signals,
            "semantic": {
                "below_axes": semantic_below_axes,
                "all_satisfied": not semantic_below_axes,
            },
            "missing_mapping": len(units_without_leaf_mapping),
            "missing_leaf": len(missing_leaf_task_ids),
            "missing_contract": len(query_signals["missing_ids"]),
            "final_empty": final_empty,
        }
        aggregation_error = aggregation.aggregation_error.strip()
        if aggregation_error:
            signals["aggregation_error"] = 1

        if not actions:
            fallback_nodes = self._fallback_action_nodes(
                plan=plan,
                query_missing_ids=missing_requirement_ids,
                missing_leaf_task_ids=missing_leaf_task_ids,
                leaf_tasks=leaf_tasks,
                units_without_leaf_mapping=units_without_leaf_mapping,
                missing_final_domain_ids=domain_signals["missing_ids_in_final"],
                missing_plan_domain_ids=domain_signals["missing_ids_in_plan"],
                missing_evidence_domain_ids=domain_signals["missing_ids_in_evidence"],
                unsupported_final_domain_ids=domain_signals["unsupported_final_ids"],
                semantic_below_axes=semantic_below_axes,
                final_empty=final_empty,
                aggregation_error=bool(aggregation_error),
            )
            if fallback_nodes:
                semantic_reason = ""
                if semantic_below_axes:
                    semantic_reason = (
                        " semantic_axes_below="
                        + ",".join(semantic_below_axes)
                        + "."
                    )
                actions = [
                    {
                        "node": min(fallback_nodes),
                        "reason": (
                        "coverage gaps remain across query/domain/layer review: "
                            f"missing_query={len(missing_requirement_ids)}, "
                            f"missing_domains={len(domain_signals['missing_ids_in_final'])}, "
                            f"missing_plan_domains={len(domain_signals['missing_ids_in_plan'])}, "
                            f"missing_evidence_domains={len(domain_signals['missing_ids_in_evidence'])}, "
                            f"unsupported_final_domains={len(domain_signals['unsupported_final_ids'])}, "
                            f"missing_leaf={len(missing_leaf_task_ids)}, "
                            f"missing_mapping={len(units_without_leaf_mapping)}, "
                            f"aggregation_error={int(bool(aggregation_error))}."
                            + semantic_reason
                        ),
                    }
                ]

        coverage_feedback = self._build_coverage_feedback(
            signals=signals,
            self_assessment=self_assessment,
        )
        return ReviewResult(
            actions=actions,
            coverage_feedback=coverage_feedback,
            now_utc=now_utc,
            quant_axes=quant_axes,
            status="pass" if not actions else "revise",
        )

    def _query_spec_blob(self, plan: Plan) -> dict[str, Any]:
        blob = asdict(plan.analysis)
        breakdown = build_query_breakdown(plan.analysis)
        blob["domains"] = self._active_domain_ids(plan)
        blob["units"] = [
            {
                "index": idx,
                **unit,
            }
            for idx, unit in enumerate(blob["units"])
        ]
        blob["query_breakdown"] = {
            "steps": [asdict(step) for step in breakdown.steps],
            "entities": [asdict(entity) for entity in breakdown.entities],
            "relations": [asdict(relation) for relation in breakdown.relations],
        }
        return blob

    def _plan_layer(self, plan: Plan) -> dict[str, Any]:
        leaf_tasks = [task for task in plan.tasks if task.task_type == "leaf"]
        planned_unit_ids = sorted(
            {unit_id for task in leaf_tasks for unit_id in task.query_unit_ids}
        )
        planned_domain_ids = sorted(self._used_modules_in_plan(plan))
        return {
            "unit_ids": planned_unit_ids,
            "domain_ids": planned_domain_ids,
            "task_ids": [task.id for task in plan.tasks],
        }

    def _execution_layer(
        self,
        plan: Plan,
        completed_leaf_ids: set[str],
    ) -> dict[str, Any]:
        leaf_tasks = {task.id: task for task in plan.tasks if task.task_type == "leaf"}
        executed_unit_ids = sorted(
            {
                unit_id
                for task_id, task in leaf_tasks.items()
                if task_id in completed_leaf_ids
                for unit_id in task.query_unit_ids
            }
        )
        return {
            "leaf_task_ids": sorted(completed_leaf_ids),
            "unit_ids": executed_unit_ids,
        }

    def _aggregation_layer(
        self,
        plan: Plan,
        aggregation: AggregationResult,
    ) -> dict[str, Any]:
        return {
            "aggregated_query_unit_ids": sorted(
                set(aggregation.aggregated_query_unit_ids)
            ),
            "final_included_query_unit_ids": sorted(
                set(aggregation.final_included_query_unit_ids)
            ),
            "mentioned_domain_ids": sorted(set(aggregation.domain_coverage.final_ids)),
            "modules_with_evidence": sorted(set(aggregation.domain_coverage.evidence_ids)),
            "active_domain_ids": self._active_domain_ids(plan),
            "plan_root_task_id": plan.root_task_id or "",
        }

    def _structural_candidate_nodes(
        self,
        *,
        unit_count: int,
        missing_leaf_task_ids: list[str],
        leaf_tasks: dict[str, Task],
        units_without_leaf_mapping: list[int],
        final_empty: bool,
    ) -> list[int]:
        if final_empty:
            return list(range(unit_count))

        nodes: set[int] = set(units_without_leaf_mapping)
        for task_id in missing_leaf_task_ids:
            task = leaf_tasks[task_id]
            nodes.update(task.query_unit_ids)
        return sorted(nodes)

    def _query_signals(
        self,
        *,
        requirements: list[QueryRequirement],
        missing_requirement_ids: list[str],
    ) -> dict[str, Any]:
        item_map = {item.id: item for item in requirements}
        missing_unit_ids: set[int] = set()
        for item_id in missing_requirement_ids:
            item = item_map.get(item_id)
            if item is None:
                continue
            missing_unit_ids.update(item.unit_ids)
        total = len(requirements)
        covered = max(total - len(missing_requirement_ids), 0)
        ratio = covered / total if total else 1.0
        return {
            "total": total,
            "covered": covered,
            "missing_ids": missing_requirement_ids,
            "missing_unit_ids": sorted(missing_unit_ids),
            "ratio": ratio,
        }

    def _unit_signals(
        self,
        *,
        unit_count: int,
        completed_leaf_ids: set[str],
        leaf_tasks: dict[str, Task],
        aggregated_query_unit_ids: list[int],
        final_included_query_unit_ids: list[int],
        missing_requirement_ids: list[str],
        requirements: list[QueryRequirement],
        final_empty: bool,
    ) -> dict[str, Any]:
        executed_unit_ids = sorted(
            {
                unit_id
                for task_id, task in leaf_tasks.items()
                if task_id in completed_leaf_ids
                for unit_id in task.query_unit_ids
            }
        )
        missing_unit_ids = set(
            self._query_signals(
                requirements=requirements,
                missing_requirement_ids=missing_requirement_ids,
            )["missing_unit_ids"]
        )
        final_unit_ids = (
            []
            if final_empty
            else sorted(
                set(final_included_query_unit_ids)
                or {
                    unit_id
                    for unit_id in range(unit_count)
                    if unit_id not in missing_unit_ids
                }
            )
        )
        return {
            "total": unit_count,
            "planned": unit_count,
            "executed": len(executed_unit_ids),
            "aggregated": len(set(aggregated_query_unit_ids)),
            "final": len(final_unit_ids),
            "planned_ids": list(range(unit_count)),
            "executed_ids": executed_unit_ids,
            "aggregated_ids": sorted(set(aggregated_query_unit_ids)),
            "final_ids": final_unit_ids,
        }

    def _domain_signals(
        self,
        *,
        plan: Plan,
        aggregation: AggregationResult,
        missing_final_domain_ids: list[str],
    ) -> dict[str, Any]:
        active_ids = self._active_domain_ids(plan)
        planned_ids = sorted(self._used_modules_in_plan(plan))
        evidence_ids = sorted(set(aggregation.domain_coverage.evidence_ids))
        mentioned_ids = sorted(set(aggregation.domain_coverage.final_ids))
        final_ids = sorted(
            (set(mentioned_ids) & set(active_ids)) - set(missing_final_domain_ids)
        )
        missing_ids_in_final = sorted(
            ((set(active_ids) - set(mentioned_ids)) | set(missing_final_domain_ids))
        )
        missing_ids_in_evidence = sorted(set(active_ids) - set(evidence_ids))
        unsupported_final_ids = sorted(set(final_ids) - set(evidence_ids))
        return {
            "selected_total": len(active_ids),
            "planned": len(planned_ids),
            "executed": len(evidence_ids),
            "final": len(final_ids),
            "selected_ids": active_ids,
            "planned_ids": planned_ids,
            "executed_ids": evidence_ids,
            "mentioned_ids": mentioned_ids,
            "final_ids": final_ids,
            "missing_in_plan": len(planned_ids) < len(active_ids),
            "missing_in_final": bool(missing_ids_in_final),
            "missing_in_evidence": bool(missing_ids_in_evidence),
            "unsupported_in_final": bool(unsupported_final_ids),
            "missing_ids_in_plan": sorted(set(active_ids) - set(planned_ids)),
            "missing_ids_in_final": missing_ids_in_final,
            "missing_ids_in_evidence": missing_ids_in_evidence,
            "unsupported_final_ids": unsupported_final_ids,
        }

    def _used_modules_in_plan(self, plan: Plan) -> set[str]:
        leaf_tasks = [
            task
            for task in plan.tasks
            if task.task_type in {"leaf", "module"} and task.tool is not None
        ]
        used: set[str] = set()
        for task in leaf_tasks:
            explicit_domain_id = task.domain_id.strip()
            if explicit_domain_id:
                used.add(explicit_domain_id)
        return used

    def _fallback_action_nodes(
        self,
        *,
        plan: Plan,
        query_missing_ids: list[str],
        missing_leaf_task_ids: list[str],
        leaf_tasks: dict[str, Task],
        units_without_leaf_mapping: list[int],
        missing_final_domain_ids: list[str],
        missing_plan_domain_ids: list[str],
        missing_evidence_domain_ids: list[str],
        unsupported_final_domain_ids: list[str],
        semantic_below_axes: list[str],
        final_empty: bool,
        aggregation_error: bool,
    ) -> list[int]:
        if final_empty:
            return list(range(len(plan.analysis.units)))

        nodes: set[int] = set(units_without_leaf_mapping)
        item_map = {item.id: item for item in plan.analysis.requirements}
        for item_id in query_missing_ids:
            item = item_map.get(item_id)
            if item is None:
                continue
            nodes.update(item.unit_ids)
        for task_id in missing_leaf_task_ids:
            task = leaf_tasks[task_id]
            nodes.update(task.query_unit_ids)
        gap_domain_ids = set(missing_final_domain_ids)
        gap_domain_ids.update(missing_plan_domain_ids)
        gap_domain_ids.update(missing_evidence_domain_ids)
        gap_domain_ids.update(unsupported_final_domain_ids)
        for domain_id in gap_domain_ids:
            for idx, unit in enumerate(plan.analysis.units):
                if domain_id in unit.domain_ids:
                    nodes.add(idx)
        if (semantic_below_axes or aggregation_error) and not nodes:
            return list(range(len(plan.analysis.units)))
        return sorted(nodes)

    def _semantic_below_axes(self, quant_axes: dict[str, Any]) -> list[str]:
        return sorted(
            axis_name
            for axis_name, payload in quant_axes.items()
            if str(payload["grade"]).strip().lower() == "below"
        )

    def _build_coverage_feedback(
        self, *, signals: dict[str, Any], self_assessment: dict[str, Any]
    ) -> dict[str, Any]:
        decomposition = self_assessment["decomposition"]["verdict"]
        execution = self_assessment["execution"]["verdict"]
        propagation = self_assessment["propagation"]["verdict"]
        units = signals["units"]
        domains = signals["domains"]
        query = signals["query"]
        summary = (
            f"decomposition={decomposition}, execution={execution}, propagation={propagation} | "
            f"query={query['covered']}/{query['total']}, "
            f"units(plan={units['planned']}/{units['total']}, exec={units['executed']}/{units['total']}, "
            f"agg={units['aggregated']}/{units['total']}, final={units['final']}/{units['total']}), "
            f"domains(plan={domains['planned']}/{domains['selected_total']}, exec={domains['executed']}/{domains['selected_total']}, "
            f"final={domains['final']}/{domains['selected_total']}, "
            f"unsupported={int(domains['unsupported_in_final'])}), "
            f"semantic_below={len(signals['semantic']['below_axes'])}, "
            f"aggregation_error={int(bool(signals.get('aggregation_error', 0)))}"
        )
        return {
            "summary": summary,
            "self_assessment": self_assessment,
            "signals": signals,
        }

    def _collapse_actions(
        self, actions_raw: list[dict[str, Any]], unit_count: int
    ) -> list[dict[str, Any]]:
        reason_by_node: dict[int, list[str]] = {}
        for action in actions_raw:
            node = action["node"]
            reason = action["reason"].strip()
            if node < 0 or node >= unit_count:
                continue
            if not reason:
                continue
            reason_by_node.setdefault(node, []).append(reason)
        return [
            {"node": node, "reason": " ".join(dict.fromkeys(reasons))}
            for node, reasons in sorted(reason_by_node.items())
            if reasons
        ]

    def _active_domain_ids(self, plan: Plan) -> list[str]:
        if self._domain_context is None or not self._domain_context.module_ids:
            return list(plan.analysis.domain_ids)
        return [
            module_id
            for module_id in self._domain_context.module_ids
            if module_id in self._domain_context.modules
        ]

    def _current_now_utc_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


Review = Reviewer
