from __future__ import annotations

import re
from typing import Any

from ...domain import RubricAspect
from ..contracts.plan import AspectFacts, ExtractionResult

_ASPECT_HEADER_RE = re.compile(
    r"^###\s+\[ASPECT:(?P<aspect_id>[^\]]+)\]\s*(?P<label>.*)$",
    re.MULTILINE,
)


class StructuredExtractor:
    """Map phase: convert free-form content into aspect-keyed facts."""

    def __init__(self, client: Any | None = None) -> None:
        self.client = client

    async def extract(
        self,
        content: str,
        rubric: list[RubricAspect],
        *,
        is_aspect_tagged: bool = False,
    ) -> ExtractionResult:
        text = (content or "").strip()
        if not text:
            missing = [aspect.id for aspect in rubric]
            return ExtractionResult(aspect_facts=[], uncovered_aspects=missing)
        if is_aspect_tagged or _ASPECT_HEADER_RE.search(text):
            return self._parse_tagged(text, rubric)
        if hasattr(self.client, "generate_json"):
            result = await self._extract_with_llm(text, rubric)
            if result.aspect_facts:
                return result
        return self._extract_with_keywords(text, rubric)

    def _parse_tagged(
        self,
        content: str,
        rubric: list[RubricAspect],
    ) -> ExtractionResult:
        matches = list(_ASPECT_HEADER_RE.finditer(content))
        if not matches:
            return self._extract_with_keywords(content, rubric)

        aspect_facts: list[AspectFacts] = []
        found_ids: set[str] = set()
        for index, match in enumerate(matches):
            start = match.end()
            end = (
                matches[index + 1].start() if index + 1 < len(matches) else len(content)
            )
            aspect_id = match.group("aspect_id").strip()
            if not aspect_id:
                continue
            section = content[start:end].strip()
            if not section:
                continue
            found_ids.add(aspect_id)
            facts = _parse_key_values(section)
            if not facts:
                facts = {"summary": section}
            evidence = _trim_evidence(section)
            aspect_facts.append(
                AspectFacts(
                    aspect_id=aspect_id,
                    facts=facts,
                    evidence=evidence,
                )
            )

        uncovered = [aspect.id for aspect in rubric if aspect.id not in found_ids]
        return ExtractionResult(
            aspect_facts=aspect_facts,
            uncovered_aspects=uncovered,
        )

    async def _extract_with_llm(
        self,
        content: str,
        rubric: list[RubricAspect],
    ) -> ExtractionResult:
        if self.client is None or not rubric:
            return ExtractionResult()
        prompt = (
            "Extract structured aspect facts from the text.\n"
            "Return only JSON.\n\n"
            "[RUBRIC]\n"
            f"{_rubric_text(rubric)}\n\n"
            "[TEXT]\n"
            f"{content}\n"
        )
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["aspect_facts", "uncovered_aspects"],
            "properties": {
                "aspect_facts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["aspect_id", "facts", "evidence"],
                        "properties": {
                            "aspect_id": {"type": "string"},
                            "facts": {
                                "type": "object",
                                "additionalProperties": {"type": "string"},
                            },
                            "evidence": {"type": "string"},
                        },
                    },
                },
                "uncovered_aspects": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        }
        try:
            payload = await self.client.generate_json(
                prompt=prompt,
                system_prompt="Return concise JSON only. No markdown.",
                response_json_schema=schema,
                trace_method="aggregator.extractor",
            )
        except Exception:
            return ExtractionResult()

        raw_facts = payload.get("aspect_facts") if isinstance(payload, dict) else None
        raw_uncovered = (
            payload.get("uncovered_aspects") if isinstance(payload, dict) else None
        )
        aspect_facts: list[AspectFacts] = []
        if isinstance(raw_facts, list):
            for item in raw_facts:
                if not isinstance(item, dict):
                    continue
                aspect_id = str(item.get("aspect_id") or "").strip()
                facts = item.get("facts")
                if not aspect_id or not isinstance(facts, dict):
                    continue
                cleaned_facts = {
                    str(key).strip(): str(value).strip()
                    for key, value in facts.items()
                    if str(key).strip() and str(value).strip()
                }
                aspect_facts.append(
                    AspectFacts(
                        aspect_id=aspect_id,
                        facts=cleaned_facts,
                        evidence=str(item.get("evidence") or "").strip(),
                    )
                )
        uncovered = (
            [str(item).strip() for item in raw_uncovered if str(item).strip()]
            if isinstance(raw_uncovered, list)
            else []
        )
        return ExtractionResult(
            aspect_facts=aspect_facts,
            uncovered_aspects=list(dict.fromkeys(uncovered)),
        )

    def _extract_with_keywords(
        self,
        content: str,
        rubric: list[RubricAspect],
    ) -> ExtractionResult:
        paragraphs = [
            block.strip() for block in re.split(r"\n\s*\n", content) if block.strip()
        ]
        if not rubric:
            return ExtractionResult(
                aspect_facts=[
                    AspectFacts(
                        aspect_id="_uncategorized",
                        facts={"summary": content},
                        evidence=_trim_evidence(content),
                    )
                ],
                uncovered_aspects=[],
            )

        matched_ids: set[str] = set()
        used_paragraphs: set[int] = set()
        aspect_facts: list[AspectFacts] = []
        for aspect in rubric:
            keywords = _aspect_keywords(aspect)
            matched = [
                paragraph
                for idx, paragraph in enumerate(paragraphs)
                if idx not in used_paragraphs and _matches_keywords(paragraph, keywords)
            ]
            if not matched:
                continue
            matched_ids.add(aspect.id)
            evidence = _trim_evidence("\n\n".join(matched))
            facts = {"summary": " ".join(matched)}
            aspect_facts.append(
                AspectFacts(aspect_id=aspect.id, facts=facts, evidence=evidence)
            )
            for idx, paragraph in enumerate(paragraphs):
                if paragraph in matched:
                    used_paragraphs.add(idx)

        leftovers = [
            paragraph
            for idx, paragraph in enumerate(paragraphs)
            if idx not in used_paragraphs
        ]
        if leftovers:
            aspect_facts.append(
                AspectFacts(
                    aspect_id="_uncategorized",
                    facts={"summary": " ".join(leftovers)},
                    evidence=_trim_evidence("\n\n".join(leftovers)),
                )
            )

        uncovered = [aspect.id for aspect in rubric if aspect.id not in matched_ids]
        return ExtractionResult(
            aspect_facts=aspect_facts,
            uncovered_aspects=uncovered,
        )


def _rubric_text(rubric: list[RubricAspect]) -> str:
    return "\n".join(
        f"- {aspect.id} ({aspect.priority}): {aspect.label} - {aspect.description}"
        for aspect in rubric
    )


def _parse_key_values(section: str) -> dict[str, str]:
    facts: dict[str, str] = {}
    for raw_line in section.splitlines():
        line = raw_line.strip().lstrip("-").strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().strip("*")
        value = value.strip()
        if key and value:
            facts[key] = value
    return facts


def _aspect_keywords(aspect: RubricAspect) -> set[str]:
    tokens = re.split(
        r"[^0-9A-Za-z가-힣_]+", f"{aspect.id} {aspect.label} {aspect.description}"
    )
    return {token.lower() for token in tokens if len(token.strip()) >= 2}


def _matches_keywords(text: str, keywords: set[str]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def _trim_evidence(text: str, limit: int = 1000) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."
