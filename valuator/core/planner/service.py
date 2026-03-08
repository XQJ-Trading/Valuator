from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any

from ...domain import (
    DomainModule,
    DomainModuleContext,
    QueryAnalysis,
    QueryIntent,
    QueryUnit,
)
from ...models.gemini_direct import GeminiClient
from ...tools.specs import (
    ToolExecutionContext,
    filter_tool_names,
    get_tool_spec,
    registered_tool_names,
)
from ...utils.config import config
from ..contracts.plan import Plan, ReviewResult, Task, ToolCall

_SYSTEM_PROMPT = (
    "Return concise JSON only. No markdown. "
    "Do not include any keys except the requested schema."
)
_LEAF_BUILD_CONCURRENCY = 4
_MAX_LEAF_ATTEMPTS_PER_UNIT = 2
_PREFERRED_SPECIALIST_TOOLS = (
    "dcf_pipeline_tool",
    "ceo_analysis_tool",
    "balance_sheet_extraction_tool",
)
_DOMAIN_TOOL_NAMES = frozenset(_PREFERRED_SPECIALIST_TOOLS)


class Planner:
    def __init__(
        self,
        client: GeminiClient | None = None,
    ) -> None:
        self.client = client or GeminiClient(config.agent_model)
        self._now_utc: datetime | None = None
        self._domain_context: DomainModuleContext | None = None

    def bind_now_utc(self, now_utc: datetime) -> None:
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        self._now_utc = now_utc.astimezone(timezone.utc)

    def bind_usage_writer(self, usage_writer: Any | None) -> None:
        self.client.bind_usage_writer(usage_writer)

    def bind_domain_context(
        self,
        domain_context: DomainModuleContext | None,
    ) -> None:
        self._domain_context = domain_context

    async def plan(self, query: str) -> Plan:
        if not query or not query.strip():
            raise ValueError("query is required")

        analysis = self._required_query_analysis()
        reference_date = self._reference_date()
        tasks = await self._build_tasks(
            query=query,
            analysis=analysis,
            reference_date=reference_date,
        )
        return Plan(
            query=query,
            analysis=analysis,
            root_task_id="T-ROOT",
            tasks=tasks,
        )

    async def replan(self, current_plan: Plan, review: ReviewResult) -> Plan:
        action_map = self._action_reasons_by_unit(
            actions=review.actions,
            unit_count=len(current_plan.analysis.units),
        )
        if not action_map:
            return current_plan

        coverage_feedback = review.coverage_feedback or {}
        signals = coverage_feedback.get("signals") or {}
        domain_signals = self._domain_signals_from_feedback(signals)
        domain_hint = ""
        if domain_signals["missing_in_plan"] or domain_signals["missing_in_final"]:
            lines: list[str] = []
            missing_plan = domain_signals["missing_ids_in_plan"]
            missing_final = domain_signals["missing_ids_in_final"]
            if missing_plan:
                lines.append(
                    f"- Plan에 사용되지 않은 도메인: {', '.join(missing_plan)}"
                )
            if missing_final:
                lines.append(
                    f"- Final에 언급되지 않은 도메인: {', '.join(missing_final)}"
                )
            if lines:
                domain_hint = "[DOMAIN_COVERAGE_GAP]\n" + "\n".join(lines)

        item_map = self._requirements_by_unit(current_plan.analysis.requirements)
        attempts_by_unit = self._leaf_attempts_by_unit(current_plan.tasks)
        existing_signatures = self._existing_leaf_signatures(current_plan.tasks)
        next_leaf_num = self._next_leaf_number(current_plan.tasks)
        reference_date = self._reference_date()
        sem = asyncio.Semaphore(_LEAF_BUILD_CONCURRENCY)

        async def _refresh(unit_idx: int, leaf_number: int) -> Task | None:
            async with sem:
                if attempts_by_unit.get(unit_idx, 0) >= _MAX_LEAF_ATTEMPTS_PER_UNIT:
                    return None
                unit = current_plan.analysis.units[unit_idx]
                focused_query = self._focused_unit_text(
                    unit=unit,
                    items=item_map.get(unit_idx, []),
                    reasons=action_map[unit_idx],
                    domain_coverage_hint=domain_hint,
                )
                focused_unit = replace(unit, retrieval_query=focused_query)
                tool = await self._select_tool_for_unit(
                    query=current_plan.query,
                    unit=focused_unit,
                    reference_date=reference_date,
                    exclude_domain_tools=True,
                )
                if self._leaf_signature(unit_idx, tool) in existing_signatures:
                    return None
                task_id = self._leaf_id(leaf_number)
                return Task(
                    id=task_id,
                    task_type="leaf",
                    query_unit_ids=[unit_idx],
                    tool=tool,
                    domain_id=self._task_domain_id_from_unit(unit),
                    output=f"/execution/outputs/{task_id}/result.md",
                    description=unit.objective,
                    node_goal=unit.objective,
                )

        refreshed_tasks = list(
            await asyncio.gather(
                *[
                    _refresh(idx, next_leaf_num + offset)
                    for offset, idx in enumerate(sorted(action_map))
                ]
            )
        )
        new_tasks = [task for task in refreshed_tasks if task is not None]
        if not new_tasks:
            return current_plan

        parent_ids_by_unit = self._refresh_parent_ids_by_unit(current_plan.tasks)
        refreshed_ids_by_parent: dict[str, list[str]] = {}
        root_id = current_plan.root_task_id or "T-ROOT"
        for task in new_tasks:
            unit_id = task.query_unit_ids[0]
            parent_id = parent_ids_by_unit.get(unit_id, root_id)
            refreshed_ids_by_parent.setdefault(parent_id, []).append(task.id)

        updated_tasks: list[Task] = []
        for task in current_plan.tasks:
            if task.id not in refreshed_ids_by_parent:
                updated_tasks.append(task)
                continue
            updated_tasks.append(
                replace(task, deps=[*task.deps, *refreshed_ids_by_parent[task.id]])
            )

        updated_tasks.extend(new_tasks)
        return replace(current_plan, tasks=updated_tasks)

    async def _build_tasks(
        self,
        *,
        query: str,
        analysis: QueryAnalysis,
        reference_date: date,
    ) -> list[Task]:
        tasks: list[Task] = []
        sem = asyncio.Semaphore(_LEAF_BUILD_CONCURRENCY)

        async def _build_leaf(unit_idx: int, unit: QueryUnit) -> tuple[Task, Task]:
            async with sem:
                tool = await self._select_tool_for_unit(
                    query=query,
                    unit=unit,
                    reference_date=reference_date,
                    exclude_domain_tools=True,
                )
                leaf_id = self._leaf_id(unit_idx + 1)
                merge_id = self._merge_id(unit_idx + 1)
                leaf_task = Task(
                    id=leaf_id,
                    task_type="leaf",
                    query_unit_ids=[unit_idx],
                    tool=tool,
                    domain_id=self._task_domain_id_from_unit(unit),
                    output=f"/execution/outputs/{leaf_id}/result.md",
                    description=unit.objective,
                    node_goal=unit.objective,
                    depth=2,
                )
                merge_task = Task(
                    id=merge_id,
                    task_type="merge",
                    query_unit_ids=[unit_idx],
                    deps=[leaf_id],
                    description=unit.objective,
                    node_goal=unit.objective,
                    depth=1,
                    merge_instruction=(
                        "Combine child analyses into one coherent sub-report. "
                        "Preserve quantitative facts, table coordinates, and source-backed claims."
                    ),
                )
                return leaf_task, merge_task

        built_units = list(
            await asyncio.gather(
                *[_build_leaf(idx, unit) for idx, unit in enumerate(analysis.units)]
            )
        )

        unit_merge_ids: dict[int, str] = {}
        root_deps: list[str] = []
        for unit_idx, (leaf_task, merge_task) in enumerate(built_units):
            tasks.append(leaf_task)
            tasks.append(merge_task)
            unit_merge_ids[unit_idx] = merge_task.id
            root_deps.append(merge_task.id)

        ctx = ToolExecutionContext(
            intent=self._intent,
            reference_year=reference_date.year,
            query=query,
            unit_query=query,
        )
        next_module_num = 1
        for module_id in self._active_module_ids():
            relevant_unit_ids = [
                idx
                for idx, unit in enumerate(analysis.units)
                if module_id in unit.domain_ids
            ]
            if not relevant_unit_ids:
                continue
            module = self._domain_context.modules[module_id]
            tool_name = self._primary_domain_tool_name(module)
            if tool_name is None:
                continue
            tool_spec = get_tool_spec(tool_name)
            if not tool_spec.accepts(self._intent):
                continue
            args = tool_spec.build_args(ctx)
            dep_ids = [
                unit_merge_ids[idx]
                for idx in relevant_unit_ids
                if idx in unit_merge_ids
            ]
            if not dep_ids:
                continue
            task_id = self._module_id(next_module_num)
            next_module_num += 1
            tasks.append(
                Task(
                    id=task_id,
                    task_type="module",
                    query_unit_ids=list(relevant_unit_ids),
                    deps=dep_ids,
                    tool=ToolCall(name=tool_name, args=args),
                    domain_id=module_id,
                    output=f"/execution/outputs/{task_id}/result.md",
                    description=module.name,
                    node_goal=module.description or module.name,
                    depth=1,
                )
            )
            root_deps.append(task_id)

        tasks.append(
            Task(
                id="T-ROOT",
                task_type="merge",
                query_unit_ids=list(range(len(analysis.units))),
                deps=root_deps,
                description=query.strip(),
                node_goal=query.strip(),
                depth=0,
                merge_instruction=self._root_merge_instruction(
                    analysis=analysis,
                ),
            )
        )
        return tasks

    def _required_query_analysis(self) -> QueryAnalysis:
        if self._domain_context is None or self._domain_context.query_analysis is None:
            raise ValueError("domain context with query analysis is required")
        analysis = self._domain_context.query_analysis
        if not analysis.units:
            raise ValueError("query analysis must include units")
        if not analysis.requirements:
            raise ValueError("query analysis must include requirements")
        return analysis

    def _choose_tool_deterministic(
        self,
        unit: QueryUnit,
        query: str,
        reference_date: date,
    ) -> ToolCall:
        allowed = self._allowed_tools_for_context()
        ctx = ToolExecutionContext(
            intent=self._intent,
            reference_year=reference_date.year,
            query=query,
            unit_query=unit.retrieval_query,
        )

        for name in _PREFERRED_SPECIALIST_TOOLS:
            if name in allowed:
                args = get_tool_spec(name).build_args(ctx)
                return ToolCall(name=name, args=args)

        name = allowed[0] if allowed else "web_search_tool"
        args = get_tool_spec(name).build_args(ctx)
        return ToolCall(name=name, args=args)

    async def _select_tool_for_unit(
        self,
        *,
        query: str,
        unit: QueryUnit,
        reference_date: date | None = None,
        exclude_domain_tools: bool = False,
    ) -> ToolCall:
        ref = reference_date or self._reference_date()
        analysis = self._domain_context.query_analysis if self._domain_context else None
        if not exclude_domain_tools and analysis is not None and analysis.allowed_tools:
            return self._choose_tool_deterministic(unit, query, ref)

        allowed_tool_names = (
            self._allowed_retrieval_tools()
            if exclude_domain_tools
            else self._allowed_tools_for_context()
        )
        tools_block = "\n".join(
            f"- {name} args: {{{get_tool_spec(name).args_text()}}}; "
            f"use_for: {get_tool_spec(name).capability}"
            for name in allowed_tool_names
        )
        domain_context_block = self._domain_context_block()
        domain_context_text = (
            f"[ACTIVE_DOMAIN_MODULES]\n{domain_context_block}\n\n"
            if domain_context_block
            else ""
        )
        entity_blob = ", ".join(unit.entity_ids) if unit.entity_ids else "(none)"
        prompt = (
            "Select exactly one tool and concrete arguments for this query unit.\n"
            "Return only a valid tool contract.\n"
            "For sec_tool and yfinance_balance_sheet use LATEST_YEAR when year is required or relevant (recency first).\n\n"
            "Prefer preserving valuation/pricing coordinates (market cap, PER, PBR, price range) for equity analysis units.\n\n"
            f"[REFERENCE_DATE]\n{ref.isoformat()}\n\n"
            f"[LATEST_YEAR]\n{ref.year}\n\n"
            f"[QUERY]\n{query}\n\n"
            f"[QUERY_UNIT_OBJECTIVE]\n{unit.objective}\n\n"
            f"[QUERY_UNIT_RETRIEVAL]\n{unit.retrieval_query}\n\n"
            f"[QUERY_UNIT_DOMAINS]\n{', '.join(unit.domain_ids)}\n\n"
            f"[QUERY_UNIT_ENTITIES]\n{entity_blob}\n\n"
            f"[QUERY_UNIT_TIME_SCOPE]\n{unit.time_scope or '(none)'}\n\n"
            f"{domain_context_text}"
            f"[TOOLS]\n{tools_block}\n"
        )
        data = await self.client.generate_json(
            prompt=prompt,
            system_prompt=_SYSTEM_PROMPT,
            response_json_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["tool_name", "tool_args"],
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "enum": allowed_tool_names,
                    },
                    "tool_args": {"type": "object"},
                },
            },
            trace_method="planner._select_tool_for_unit",
        )
        name = data["tool_name"].strip()
        args = data["tool_args"]
        self._check_tool_args(name=name, args=args)
        return ToolCall(name=name, args=args)

    def _check_tool_args(
        self,
        *,
        name: str,
        args: dict[str, Any],
    ) -> None:
        spec = get_tool_spec(name)
        missing = [key for key in spec.required if key not in args]
        if missing:
            raise ValueError(f"missing required args for {name}: {missing}")
        empty_required = [
            key
            for key in spec.required
            if isinstance(args.get(key), str) and not str(args.get(key)).strip()
        ]
        if empty_required:
            raise ValueError(f"empty required args for {name}: {empty_required}")
        allowed = (*spec.required, *spec.optional)
        unknown = [key for key in args if key not in allowed]
        if unknown:
            raise ValueError(f"unknown args for {name}: {unknown}")

    def _allowed_tools_for_context(self) -> list[str]:
        module_allowed = self._module_allowed_tools()
        analysis = self._domain_context.query_analysis if self._domain_context else None
        if analysis is not None and analysis.allowed_tools:
            valid = filter_tool_names(analysis.allowed_tools, intent=self._intent)
            if module_allowed:
                scoped = sorted(name for name in valid if name in set(module_allowed))
                if scoped:
                    return scoped
                return module_allowed
            if valid:
                return sorted(valid)

        if self._domain_context is None or not self._domain_context.module_ids:
            return filter_tool_names(registered_tool_names(), intent=self._intent)

        if module_allowed:
            return module_allowed
        fallback = filter_tool_names(registered_tool_names(), intent=self._intent)
        return fallback or ["web_search_tool"]

    def _allowed_retrieval_tools(self) -> list[str]:
        base = self._allowed_tools_for_context()
        retrieval = [t for t in base if t not in _DOMAIN_TOOL_NAMES]
        return retrieval or ["web_search_tool"]

    def _module_allowed_tools(self) -> list[str]:
        if self._domain_context is None or not self._domain_context.module_ids:
            return []

        allowed: set[str] = set()
        for module_id in self._domain_context.module_ids:
            module = self._domain_context.modules.get(module_id)
            if module is None:
                continue
            for tool_name in module.tools:
                if tool_name in registered_tool_names():
                    allowed.add(tool_name)
        return filter_tool_names(allowed, intent=self._intent)

    @property
    def _ticker(self) -> str:
        return self._intent.ticker

    @property
    def _intent(self) -> QueryIntent:
        if not self._domain_context or self._domain_context.query_intent is None:
            return QueryIntent(query="")
        return self._domain_context.query_intent

    def _primary_domain_tool_name(self, module: DomainModule) -> str | None:
        for dt in module.domain_tools:
            if dt.enabled:
                return dt.tool
        return None

    def _active_module_ids(self) -> list[str]:
        if self._domain_context is None:
            return []
        return [
            module_id
            for module_id in self._domain_context.module_ids
            if module_id in self._domain_context.modules
        ]

    def _refresh_parent_ids_by_unit(self, tasks: list[Task]) -> dict[int, str]:
        parent_by_child: dict[str, list[Task]] = {}
        for task in tasks:
            for dep_id in task.deps:
                parent_by_child.setdefault(dep_id, []).append(task)

        parent_ids_by_unit: dict[int, str] = {}
        for task in tasks:
            if task.task_type != "leaf" or not task.query_unit_ids:
                continue
            parents = parent_by_child.get(task.id, [])
            if not parents:
                continue
            parents.sort(key=lambda parent: parent.depth, reverse=True)
            parent_ids_by_unit[task.query_unit_ids[0]] = parents[0].id
        return parent_ids_by_unit

    def _next_leaf_number(self, tasks: list[Task]) -> int:
        max_num = 0
        for task in tasks:
            if not task.id.startswith("T-LEAF-"):
                continue
            suffix = task.id.removeprefix("T-LEAF-")
            if suffix.isdigit():
                max_num = max(max_num, int(suffix))
        return max_num + 1

    def _leaf_attempts_by_unit(self, tasks: list[Task]) -> dict[int, int]:
        attempts: dict[int, int] = {}
        for task in tasks:
            if task.task_type != "leaf" or len(task.query_unit_ids) != 1:
                continue
            unit_id = task.query_unit_ids[0]
            attempts[unit_id] = attempts.get(unit_id, 0) + 1
        return attempts

    def _existing_leaf_signatures(self, tasks: list[Task]) -> set[tuple[int, str, str]]:
        signatures: set[tuple[int, str, str]] = set()
        for task in tasks:
            if task.task_type != "leaf" or task.tool is None or len(task.query_unit_ids) != 1:
                continue
            signatures.add(self._leaf_signature(task.query_unit_ids[0], task.tool))
        return signatures

    def _leaf_signature(self, unit_id: int, tool: ToolCall) -> tuple[int, str, str]:
        return (
            unit_id,
            tool.name,
            json.dumps(tool.args, ensure_ascii=False, sort_keys=True),
        )

    def _leaf_id(self, number: int) -> str:
        return f"T-LEAF-{number}"

    def _merge_id(self, number: int) -> str:
        return f"T-MERGE-{number}"

    def _module_id(self, number: int) -> str:
        return f"T-MOD-{number}"

    def _reference_date(self) -> date:
        if self._now_utc is not None:
            return self._now_utc.date()
        return date.today()

    def _root_merge_instruction(
        self,
        *,
        analysis: QueryAnalysis,
    ) -> str:
        instructions = [
            "Combine all child analyses into a single coherent investment report.",
            "Use absolute time anchors (for example, 2025Q3, 2026-01-08) instead of relative phrases.",
            "Preserve quantitative facts, explain risk transmission to P&L/FCF, and conclude with trigger-based portfolio actions.",
        ]
        intent_tags = {tag.strip().lower() for tag in analysis.intent_tags if tag.strip()}
        if "recommendation" in intent_tags or "screening" in intent_tags:
            instructions.append(
                "Preserve the user's recommendation intent instead of rewriting the answer into a generic market essay."
            )
            instructions.append(
                "State explicit candidate picks or shortlist outputs that are directly responsive to the query, including why each name is selected and when not to buy it."
            )
            instructions.append(
                "Honor any market, count, style, or portfolio constraints that are present in the query or child analyses."
            )
        if "comparison" in intent_tags:
            instructions.append(
                "Keep the response in comparison form and do not collapse it into a single-name recommendation."
            )
        if not self._has_concrete_subject():
            instructions.append(
                "Do not fabricate a single-company subject or placeholder issuer when the query is about a basket or recommendation set."
            )
        return " ".join(instructions)

    def _action_reasons_by_unit(
        self,
        *,
        actions: Any,
        unit_count: int,
    ) -> dict[int, list[str]]:
        if not actions:
            return {}
        reason_map: dict[int, list[str]] = {}
        for action in actions:
            node = action["node"]
            reason = action["reason"].strip()
            if node < 0 or node >= unit_count or not reason:
                continue
            reason_map.setdefault(node, []).append(reason)
        return {
            node: list(dict.fromkeys(reasons))
            for node, reasons in reason_map.items()
            if reasons
        }

    def _requirements_by_unit(
        self,
        requirements: list[Any],
    ) -> dict[int, list[Any]]:
        by_unit: dict[int, list[Any]] = {}
        for item in requirements:
            for unit_id in item.unit_ids:
                by_unit.setdefault(unit_id, []).append(item)
        return by_unit

    def _focused_unit_text(
        self,
        *,
        unit: QueryUnit,
        items: list[Any],
        reasons: list[str],
        domain_coverage_hint: str = "",
    ) -> str:
        chunks: list[str] = [
            f"[OBJECTIVE]\n{unit.objective}",
            f"[RETRIEVAL]\n{unit.retrieval_query}",
        ]
        if unit.domain_ids:
            chunks.append(f"[DOMAINS]\n{', '.join(unit.domain_ids)}")
        if unit.entity_ids:
            chunks.append(f"[ENTITIES]\n{', '.join(unit.entity_ids)}")
        if unit.time_scope.strip():
            chunks.append(f"[TIME_SCOPE]\n{unit.time_scope.strip()}")
        if domain_coverage_hint.strip():
            chunks.append(domain_coverage_hint.strip())
        if items:
            lines = [f"- [{item.id}] {item.acceptance}" for item in items]
            chunks.append("[REQUIREMENTS TO FILL]\n" + "\n".join(lines))
        if reasons:
            seen: set[str] = set()
            reason_lines: list[str] = []
            for reason in reasons:
                text = reason.strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                reason_lines.append(f"- {text}")
            if reason_lines:
                chunks.append("[REVIEW_GAPS]\n" + "\n".join(reason_lines))
        return "\n\n".join(chunks)

    def _task_domain_id_from_unit(self, unit: QueryUnit) -> str:
        if len(unit.domain_ids) == 1:
            return unit.domain_ids[0]
        return ""

    def _has_concrete_subject(self) -> bool:
        subject = self._intent
        return any(
            (
                subject.company_name.strip(),
                subject.ticker.strip(),
                subject.security_code.strip(),
            )
        )

    def _domain_context_block(self) -> str:
        ctx = self._domain_context
        if ctx is None or not ctx.module_ids:
            return ""

        lines: list[str] = []
        for module_id in ctx.module_ids:
            module = ctx.modules.get(module_id)
            if module is None:
                continue
            lines.append(f"- module={module.id} name={module.name}")
            if module.tools:
                lines.append(f"  - tools={', '.join(module.tools)}")
            for req in module.report_contract:
                text = req.text.strip()
                if text:
                    lines.append(f"  - report_requirement={text}")
            fragment = module.prompt_fragment.strip()
            if fragment:
                lines.append(f"  - prompt_fragment={fragment}")
        return "\n".join(lines)

    def _domain_signals_from_feedback(self, signals: dict[str, Any]) -> dict[str, Any]:
        raw = signals.get("domains") or signals.get("domain") or {}
        if raw:
            missing_ids_in_plan = list(raw.get("missing_ids_in_plan") or [])
            missing_ids_in_final = list(raw.get("missing_ids_in_final") or [])
            return {
                "missing_in_plan": bool(raw.get("missing_in_plan")),
                "missing_in_final": bool(raw.get("missing_in_final")),
                "missing_ids_in_plan": missing_ids_in_plan,
                "missing_ids_in_final": missing_ids_in_final,
            }

        return {
            "missing_in_plan": bool(signals.get("domain_missing_in_plan")),
            "missing_in_final": bool(signals.get("domain_missing_in_final")),
            "missing_ids_in_plan": list(
                signals.get("domain_missing_module_ids_in_plan") or []
            ),
            "missing_ids_in_final": list(
                signals.get("domain_missing_module_ids_in_final") or []
            ),
        }
