from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from ..contracts.plan import ExecutionArtifact, ReportMaterial, Task, TaskReport
from .graph_ops import descendant_artifact_task_ids, descendant_leaf_artifacts


def extract_leaf_artifacts(
    artifacts: list[ExecutionArtifact],
) -> dict[str, list[ReportMaterial]]:
    by_task: dict[str, list[ReportMaterial]] = {}
    for artifact in artifacts:
        by_task.setdefault(artifact.task_id, []).append(_build_report_material(artifact))
    return by_task


def extract_artifacts_by_task(
    artifacts: list[ExecutionArtifact],
) -> dict[str, list[ExecutionArtifact]]:
    by_task: dict[str, list[ExecutionArtifact]] = {}
    for artifact in artifacts:
        by_task.setdefault(artifact.task_id, []).append(artifact)
    return by_task


def accumulate_execution_artifact(
    artifact: ExecutionArtifact,
    artifact_materials: dict[str, list[ReportMaterial]],
    artifact_index: dict[str, list[ExecutionArtifact]],
) -> None:
    artifact_materials.setdefault(artifact.task_id, []).append(_build_report_material(artifact))
    artifact_index.setdefault(artifact.task_id, []).append(artifact)


def collect_materials(
    task: Task,
    task_map: dict[str, Task],
    leaf_artifacts: dict[str, list[ReportMaterial]],
    reports: dict[str, TaskReport],
    descendant_cache: dict[str, list[ReportMaterial]],
) -> list[ReportMaterial]:
    if task.task_type != "merge":
        return list(leaf_artifacts.get(task.id, []))

    materials: list[ReportMaterial] = []
    seen_sources: set[str] = set()
    for dep_id in task.deps:
        child_report = reports.get(dep_id)
        if child_report is None or not child_report.markdown.strip():
            continue
        source = f"report:{dep_id}"
        if source in seen_sources:
            continue
        materials.append(ReportMaterial(source=source, content=child_report.markdown, facts={}))
        seen_sources.add(source)

    for item in descendant_leaf_artifacts(task.id, task_map, leaf_artifacts, descendant_cache):
        if item.source in seen_sources:
            continue
        materials.append(replace(item))
        seen_sources.add(item.source)
    return materials


def collect_domain_artifacts(
    task: Task,
    task_map: dict[str, Task],
    artifact_index: dict[str, list[ExecutionArtifact]],
) -> list[ExecutionArtifact]:
    artifact_ids = descendant_artifact_task_ids(task.id, task_map)
    artifacts: list[ExecutionArtifact] = []
    for artifact_id in sorted(artifact_ids):
        for artifact in artifact_index.get(artifact_id, []):
            if not artifact.domain_id.strip():
                continue
            artifacts.append(artifact)
    return artifacts


def query_unit_ids_for_leaf_tasks(
    leaf_task_ids: list[str],
    task_map: dict[str, Task],
) -> list[int]:
    query_units: set[int] = set()
    for task_id in leaf_task_ids:
        task = task_map[task_id]
        query_units.update(task.query_unit_ids)
    return sorted(query_units)


def _build_report_material(artifact: ExecutionArtifact) -> ReportMaterial:
    raw_result = artifact.raw_result or {}
    content = _material_content(raw_result=raw_result, fallback=artifact.content)
    facts = _extract_key_value_facts(raw_result)
    return ReportMaterial(source=artifact.path, content=content, facts=facts)


def _material_content(*, raw_result: dict[str, Any], fallback: str) -> str:
    sections: list[str] = []

    findings = str(raw_result.get("findings") or "").strip()
    if findings:
        sections.append(findings)

    summary = str(raw_result.get("summary") or "").strip()
    if summary and summary not in sections:
        sections.append(summary)

    extract = str(raw_result.get("extract") or "").strip()
    if extract and extract not in sections:
        sections.append(extract)

    sources = _render_sources(raw_result.get("sources"))
    if sources:
        sections.append(sources)

    results = _render_batch_results(raw_result.get("results"))
    if results:
        sections.append(results)

    if sections:
        return "\n\n".join(section for section in sections if section.strip()).strip()
    return fallback.strip()


def _extract_key_value_facts(raw_result: dict[str, Any]) -> dict[str, str]:
    skip_keys = {
        "findings",
        "summary",
        "extract",
        "extracts",
        "payload",
        "form",
        "filled_form",
        "calculation",
    }
    facts: dict[str, str] = {}

    for key, value in raw_result.items():
        if key in skip_keys:
            continue
        if isinstance(value, (str, int, float, bool)):
            text = str(value).strip()
            if text:
                facts[key] = text
            continue
        if isinstance(value, dict):
            facts.update(_flatten_nested_facts(key=key, payload=value))
            continue
        if isinstance(value, list):
            rendered = _render_scalar_list(value)
            if rendered:
                facts[key] = rendered
    return facts


def _flatten_nested_facts(*, key: str, payload: dict[str, Any]) -> dict[str, str]:
    nested: dict[str, str] = {}
    for sub_key, sub_value in payload.items():
        if isinstance(sub_value, (str, int, float, bool)):
            text = str(sub_value).strip()
            if text:
                nested[f"{key}.{sub_key}"] = text
            continue
        if isinstance(sub_value, dict):
            nested.update(_flatten_nested_facts(key=f"{key}.{sub_key}", payload=sub_value))
            continue
        if isinstance(sub_value, list):
            rendered = _render_scalar_list(sub_value)
            if rendered:
                nested[f"{key}.{sub_key}"] = rendered
    return nested


def _render_sources(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    rows = [str(item).strip() for item in value if str(item).strip()]
    if not rows:
        return ""
    return "[SOURCES]\n" + "\n".join(f"- {row}" for row in rows)


def _render_batch_results(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    blocks: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        result_payload = item.get("result")
        if not isinstance(result_payload, dict):
            continue
        lines = [f"[BATCH_RESULT {index}]"]
        query = str(result_payload.get("query") or "").strip()
        if query:
            lines.append(f"- query: {query}")
        findings = str(result_payload.get("findings") or "").strip()
        if findings:
            lines.append(findings)
        sources = _render_sources(result_payload.get("sources"))
        if sources:
            lines.append(sources)
        block = "\n".join(line for line in lines if line.strip()).strip()
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)


def _render_scalar_list(values: list[Any]) -> str:
    rendered = [
        str(value).strip()
        for value in values
        if isinstance(value, (str, int, float, bool)) and str(value).strip()
    ]
    if rendered:
        return ", ".join(rendered)
    dict_rows = [
        json.dumps(item, ensure_ascii=False, sort_keys=True)
        for item in values
        if isinstance(item, dict)
    ]
    return " | ".join(dict_rows)
