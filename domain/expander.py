from __future__ import annotations

from dataclasses import replace

from .query import QueryAnalysis, QueryUnit
from .types import DomainModule, RubricAspect

EXPANSION_THRESHOLD = 3
MAX_EXPANSION_GROUPS = 2


def expand(
    analysis: QueryAnalysis,
    modules: dict[str, DomainModule],
) -> QueryAnalysis:
    """Expand coarse query units when high-priority rubric aspects are dense."""
    if not analysis.units:
        return analysis

    expanded_units: list[QueryUnit] = []
    for unit in analysis.units:
        high_priority = [
            aspect
            for aspect in _collect_aspects(unit.domain_ids, modules)
            if aspect.priority.strip().lower() == "high"
        ]
        if len(high_priority) <= EXPANSION_THRESHOLD:
            expanded_units.append(unit)
            continue

        groups = _group_by_pairs(high_priority)[:MAX_EXPANSION_GROUPS]
        if len(groups) <= 1:
            expanded_units.append(unit)
            continue

        for index, group in enumerate(groups, start=1):
            first = group[0]
            aspect_ids = ", ".join(aspect.id for aspect in group)
            aspect_labels = ", ".join(aspect.label for aspect in group)
            detail = "; ".join(
                aspect.description for aspect in group if aspect.description.strip()
            )
            retrieval = unit.retrieval_query.strip()
            if detail:
                retrieval = (
                    f"{retrieval}\n\n[ASPECT_FOCUS]\n"
                    f"ids={aspect_ids}\nlabels={aspect_labels}\n{detail}"
                ).strip()
            expanded_units.append(
                QueryUnit(
                    id=f"{unit.id}_A{index}_{first.id}",
                    objective=f"{unit.objective}: {aspect_labels}",
                    retrieval_query=retrieval,
                    domain_ids=list(unit.domain_ids),
                    entity_ids=list(unit.entity_ids),
                    time_scope=unit.time_scope,
                    parent_unit_id=unit.id,
                )
            )

    return replace(analysis, units=expanded_units)


def _collect_aspects(
    domain_ids: list[str],
    modules: dict[str, DomainModule],
) -> list[RubricAspect]:
    collected: list[RubricAspect] = []
    seen: set[tuple[str, str]] = set()
    for module_id in domain_ids:
        module = modules.get(module_id)
        if module is None:
            continue
        for aspect in module.rubric:
            key = (module_id, aspect.id)
            if key in seen:
                continue
            seen.add(key)
            collected.append(aspect)
    return collected


def _group_by_pairs(aspects: list[RubricAspect]) -> list[list[RubricAspect]]:
    return [aspects[index : index + 2] for index in range(0, len(aspects), 2)]
