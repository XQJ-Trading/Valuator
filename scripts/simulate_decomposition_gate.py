#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import string
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PUNCT_TO_SPACE = str.maketrans({char: " " for char in string.punctuation})


@dataclass
class GateProfile:
    initial_threshold: float = 0.10
    accept_penalty: float = 0.04
    reject_penalty: float = 0.25
    max_depth: int = 3
    max_children: int = 5
    weight_depth: float = 0.35
    weight_breadth: float = 0.25
    weight_token_pressure: float = 0.15
    weight_semantic_overlap: float = 0.25
    static_weight: float = 0.55
    critic_weight: float = 0.45
    semantic_overlap_threshold: float = 0.50
    max_steps_per_task: int = 60


@dataclass
class Proposal:
    task_id: str
    llm_call_index: int
    step_index: int
    children: list[dict[str, Any]]
    critic: dict[str, Any] | None
    original_accepted: bool
    original_child_ids: list[str]
    simulated_accepted: bool = False
    simulated_reason: str = ""
    static_penalty: float = 0.0


def tokens(text: str) -> set[str]:
    return {
        token
        for token in text.casefold().translate(PUNCT_TO_SPACE).split()
        if len(token) >= 2
    }


def overlap_score(left: str, right: str) -> float:
    left_tokens = tokens(left)
    right_tokens = tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    return len(left_tokens & right_tokens) / len(union)


def semantic_overlap(children: list[dict[str, Any]], existing: list[str], threshold: float) -> float:
    best = 0.0
    descriptions = [str(child["description"]) for child in children]
    for index, description in enumerate(descriptions):
        for other in descriptions[index + 1 :]:
            best = max(best, overlap_score(description, other))
        for other in existing:
            best = max(best, overlap_score(description, other))
    return best if best >= threshold else 0.0


def depth_cost(depth: int, max_depth: int) -> float:
    return (depth / max_depth) ** 2


def breadth_cost(child_count: int, max_children: int) -> float:
    if child_count <= 1:
        return 0.0
    return math.log2(child_count) / math.log2(max_children)


def token_pressure(child_count: int, depth: int, max_steps_per_task: int) -> float:
    estimated_tokens = child_count * 2000
    budget_per_branch = max_steps_per_task * 2000 / (depth + 1)
    return estimated_tokens / budget_per_branch


def penalty_to_score(penalty: float) -> float:
    return max(-0.5, min(0.5, 0.5 - penalty))


def critic_score(critic: dict[str, Any], actual_children: int) -> float:
    score = 0.0
    if critic.get("single_tool_possible"):
        score -= 0.5
    score -= 0.35 * len(critic.get("redundant_pairs", []))
    score += int(critic.get("coverage_pct", 0)) / 100.0
    excess = actual_children - int(critic.get("min_children", 0))
    if excess > 0:
        score -= 0.1 * excess
    score += 0.3 if critic.get("allow") else -0.3
    return score


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def parse_response(payload: dict[str, Any]) -> dict[str, Any] | None:
    text = payload.get("response_text")
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def step_outcomes(events: list[dict[str, Any]]) -> dict[str, dict[int, bool]]:
    current_step: dict[str, int] = defaultdict(int)
    outcomes: dict[str, dict[int, bool]] = defaultdict(dict)
    for event in events:
        task_id = event.get("task_id")
        if not isinstance(task_id, str):
            continue
        if event.get("type") == "step_start":
            current_step[task_id] += 1
            continue
        step_index = current_step.get(task_id)
        if not step_index:
            continue
        if event.get("type") == "decision":
            outcomes[task_id][step_index] = event.get("detail", {}).get("action") == "decompose"
        elif event.get("type") == "decomposition_gated":
            outcomes[task_id][step_index] = False
    return outcomes


def has_pruned_ancestor(task_id: str, pruned_roots: set[str]) -> bool:
    parts = task_id.split(".")
    for index in range(1, len(parts)):
        if ".".join(parts[:index]) in pruned_roots:
            return True
    return False


def method_task_id(method: str) -> str | None:
    for prefix in ("agent.step.", "agent.gate.critic."):
        if method.startswith(prefix):
            return method[len(prefix) :]
    return None


def collect_proposals(session_dir: Path, events: list[dict[str, Any]]) -> list[Proposal]:
    outcomes = step_outcomes(events)
    calls_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in session_dir.glob("tasks/**/llm_calls/step_*.json"):
        payload = load_json(path)
        task_id = payload.get("task_id")
        if isinstance(task_id, str):
            calls_by_task[task_id].append(payload)

    proposals: list[Proposal] = []
    actual_child_counts: dict[str, int] = defaultdict(int)

    for task_id, calls in calls_by_task.items():
        calls.sort(key=lambda item: int(item.get("llm_call_index", 0)))
        step_index = 0
        for index, payload in enumerate(calls):
            if payload.get("trace_method") != f"agent.step.{task_id}":
                continue
            step_index += 1
            parsed = parse_response(payload)
            if not isinstance(parsed, dict) or parsed.get("action") != "decompose":
                continue
            children = parsed.get("children", [])
            if not isinstance(children, list) or not children:
                continue

            critic = None
            for later in calls[index + 1 :]:
                if later.get("trace_method") == f"agent.step.{task_id}":
                    break
                if later.get("trace_method") == f"agent.gate.critic.{task_id}":
                    critic = parse_response(later)
                    break

            original_accepted = outcomes.get(task_id, {}).get(step_index, False)
            original_child_ids: list[str] = []
            if original_accepted:
                start = actual_child_counts[task_id]
                original_child_ids = [
                    f"{task_id}.{offset}"
                    for offset in range(start, start + len(children))
                ]
                actual_child_counts[task_id] += len(children)

            proposals.append(
                Proposal(
                    task_id=task_id,
                    llm_call_index=int(payload.get("llm_call_index", 0)),
                    step_index=step_index,
                    children=children,
                    critic=critic,
                    original_accepted=original_accepted,
                    original_child_ids=original_child_ids,
                )
            )

    proposals.sort(key=lambda item: item.llm_call_index)
    return proposals


def simulate(proposals: list[Proposal], profile: GateProfile) -> set[str]:
    current_children: dict[str, list[str]] = defaultdict(list)
    pruned_roots: set[str] = set()

    for proposal in proposals:
        if has_pruned_ancestor(proposal.task_id, pruned_roots):
            continue

        existing = current_children[proposal.task_id]
        total_children = len(existing) + len(proposal.children)
        penalty = (
            profile.weight_depth * depth_cost(proposal.task_id.count("."), profile.max_depth)
            + profile.weight_breadth * breadth_cost(total_children, profile.max_children)
            + profile.weight_token_pressure
            * token_pressure(total_children, proposal.task_id.count("."), profile.max_steps_per_task)
            + profile.weight_semantic_overlap
            * semantic_overlap(
                proposal.children,
                existing,
                profile.semantic_overlap_threshold,
            )
        )
        proposal.static_penalty = penalty

        if penalty <= profile.accept_penalty:
            accepted = True
            proposal.simulated_reason = "static accept"
        elif penalty >= profile.reject_penalty:
            accepted = False
            proposal.simulated_reason = "static reject"
        elif proposal.critic is None:
            accepted = penalty_to_score(penalty) > profile.initial_threshold
            proposal.simulated_reason = "threshold fallback"
        else:
            score = (
                profile.static_weight * penalty_to_score(penalty)
                + profile.critic_weight * critic_score(proposal.critic, len(proposal.children))
            )
            accepted = score > profile.initial_threshold
            proposal.simulated_reason = "critic replay"

        proposal.simulated_accepted = accepted
        if accepted:
            existing.extend(str(child["description"]) for child in proposal.children)
        elif proposal.original_accepted:
            pruned_roots.update(proposal.original_child_ids)

    return pruned_roots


def summarize(session_dir: Path, proposals: list[Proposal], pruned_roots: set[str]) -> dict[str, Any]:
    llm_usage = load_jsonl(session_dir / "diagnostics" / "llm_usage.jsonl")
    events = load_jsonl(session_dir / "diagnostics" / "events.jsonl")
    decomposition = load_json(session_dir / "plan" / "active" / "decomposition.json")

    prompt_tokens = 0
    completion_tokens = 0
    cost_usd = 0.0
    latency_ms = 0.0
    step_calls = 0
    critic_calls = 0
    tool_calls = 0

    for row in llm_usage:
        method = row.get("method", "")
        if not isinstance(method, str):
            continue
        task_id = method_task_id(method)
        if not task_id or not any(task_id.startswith(prefix) for prefix in pruned_roots):
            continue
        usage = row.get("usage", {})
        prompt_tokens += int(usage.get("prompt_tokens", 0))
        completion_tokens += int(usage.get("completion_tokens", 0))
        cost_usd += float(row.get("cost_usd", 0.0))
        latency_ms += float(row.get("latency_ms", 0.0))
        if method.startswith("agent.step."):
            step_calls += 1
        elif method.startswith("agent.gate.critic."):
            critic_calls += 1

    for event in events:
        if event.get("type") != "tool_execute":
            continue
        task_id = event.get("task_id")
        if isinstance(task_id, str) and any(task_id.startswith(prefix) for prefix in pruned_roots):
            tool_calls += 1

    avoided_tasks = sum(
        1
        for task in decomposition.get("tasks", [])
        if isinstance(task.get("id"), str)
        and any(task["id"].startswith(prefix) for prefix in pruned_roots)
    )

    top_pruned = [
        {
            "task_id": proposal.task_id,
            "step_index": proposal.step_index,
            "children": len(proposal.children),
            "static_penalty": round(proposal.static_penalty, 4),
            "reason": proposal.simulated_reason,
        }
        for proposal in proposals
        if proposal.original_accepted and not proposal.simulated_accepted
    ]
    top_pruned.sort(key=lambda item: (-item["static_penalty"], item["task_id"]))

    return {
        "proposal_count": len(proposals),
        "original_accepted_count": sum(1 for proposal in proposals if proposal.original_accepted),
        "simulated_accepted_count": sum(1 for proposal in proposals if proposal.simulated_accepted),
        "pruned_branch_roots": sorted(pruned_roots),
        "savings": {
            "avoided_tasks": avoided_tasks,
            "avoided_step_calls": step_calls,
            "avoided_critic_calls": critic_calls,
            "avoided_tool_calls": tool_calls,
            "avoided_prompt_tokens": prompt_tokens,
            "avoided_completion_tokens": completion_tokens,
            "avoided_cost_usd": round(cost_usd, 6),
            "avoided_latency_ms_cumulative": round(latency_ms, 2),
        },
        "top_pruned": top_pruned[:10],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay decomposition gate decisions on a saved session log.")
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    session_dir = args.session_dir.resolve()

    events = load_jsonl(session_dir / "diagnostics" / "events.jsonl")
    proposals = collect_proposals(session_dir, events)
    pruned_roots = simulate(proposals, GateProfile())
    summary = summarize(session_dir, proposals, pruned_roots)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    print(f"proposal_count={summary['proposal_count']}")
    print(f"original_accepted_count={summary['original_accepted_count']}")
    print(f"simulated_accepted_count={summary['simulated_accepted_count']}")
    for key, value in summary["savings"].items():
        print(f"{key}={value}")
    print("top_pruned:")
    for item in summary["top_pruned"]:
        print(
            f"- {item['task_id']} step={item['step_index']} "
            f"children={item['children']} penalty={item['static_penalty']} "
            f"reason={item['reason']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
