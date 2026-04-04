from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .knowledge import INDEX_PATH, KNOWLEDGE_ROOT, MODULES_ROOT
from .types import AcceptanceCheck, DomainIndex, DomainModule, RubricAspect

SECTION_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
ASPECT_HEADING = re.compile(
    r"^###\s+([a-z][a-z0-9_]*)\s*[—\-]\s*(.+?)\s*\[(\w+)\]\s*$",
    re.MULTILINE,
)
CHECK_ITEM = re.compile(r"^-\s+\*\*(\w+)\*\*:\s*(.+)$")
CHECK_REQUIRES = re.compile(r"^\s*[→>]\s*(.+)$")
VALID_PRIORITIES = {"high", "medium", "low"}
ASPECT_GUIDE = "### my_aspect — 분석 관점 [HIGH]"


class DomainLoader:
    """Load and validate domain modules from YAML/Markdown files."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or KNOWLEDGE_ROOT
        self._index_path = self._resolve_index_path(self._root)
        self._modules_root = self._resolve_modules_root(self._root)

    def load(self) -> tuple[DomainIndex, dict[str, DomainModule]]:
        index = DomainIndex.model_validate(self._read_yaml(self._index_path))
        modules: dict[str, DomainModule] = {}
        for module_id in index.modules:
            module_path = self._module_path(module_id)
            module = self._build_module(self._read_yaml(module_path), path=module_path)
            if module.id != module_id:
                raise ValueError(
                    f"domain module id mismatch: file={module_id}.yaml id={module.id}"
                )
            modules[module_id] = module
        self._ensure_no_cycles(modules)
        return index, modules

    def _module_path(self, module_id: str) -> Path:
        subdir_path = self._modules_root / module_id / "module.yaml"
        flat_path = self._root / f"{module_id}.yaml"
        if subdir_path.is_file():
            return subdir_path
        if flat_path.is_file():
            return flat_path
        raise FileNotFoundError(
            f"domain module config not found for '{module_id}': {subdir_path}"
        )

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise FileNotFoundError(f"domain config not found: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"domain YAML root must be a mapping: {path}")
        return data

    def _build_module(self, data: dict[str, Any], *, path: Path) -> DomainModule:
        self._validate_module_keys(data, path=path)
        base_dir = path.parent
        knowledge_ref = self._ref(data, "knowledge") or "knowledge.md"
        knowledge_path = base_dir / knowledge_ref
        if knowledge_path.is_file():
            persona, rubric, format_spec, contract = self._parse_knowledge_md(
                knowledge_path.read_text(encoding="utf-8")
            )
        else:
            persona_ref = self._ref(data, "persona", "persona_file") or "persona.md"
            rubric_ref = self._ref(data, "rubric", "rubric_file") or "rubric.yaml"
            format_ref = self._ref(data, "format", "format_file") or "format.md"
            contract_ref = self._ref(data, "contract", "contract_file") or "contract.yaml"
            persona = self._read_text(base_dir / persona_ref)
            rubric = self._load_rubric(base_dir / rubric_ref, path=path)
            format_spec = self._read_text(base_dir / format_ref)
            contract = self._load_contract(base_dir / contract_ref, path=path)
        self._validate_contract_references(rubric, contract, path=path)
        return DomainModule(
            id=str(data["id"]).strip(),
            name=str(data["name"]).strip(),
            description=str(data.get("description") or "").strip(),
            persona=persona,
            rubric=rubric,
            format_spec=format_spec,
            contract=contract,
            depends_on=self._string_list(
                data.get("depends_on"),
                field_name="depends_on",
                path=path,
            ),
        )

    def _validate_module_keys(self, data: dict[str, Any], *, path: Path) -> None:
        allowed = {
            "id",
            "name",
            "description",
            "persona",
            "persona_file",
            "rubric",
            "rubric_file",
            "format",
            "format_file",
            "contract",
            "contract_file",
            "knowledge",
            "depends_on",
        }
        unknown = sorted(key for key in data if key not in allowed)
        if unknown:
            raise ValueError(f"unsupported domain module keys in {path}: {unknown}")

    def _load_rubric(self, ref: Path, *, path: Path) -> list[RubricAspect]:
        raw = self._read_yaml(ref).get("aspects")
        if not isinstance(raw, list):
            raise ValueError(f"aspects must be a list in domain module: {path}")
        aspects: list[RubricAspect] = []
        seen_ids: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError(f"aspect item must be a mapping in domain module: {path}")
            aspect_id = str(item.get("id") or "").strip()
            label = str(item.get("label") or "").strip()
            description = str(item.get("description") or "").strip()
            priority = str(item.get("priority") or "medium").strip().lower() or "medium"
            if not aspect_id or not label or not description:
                raise ValueError(f"aspect must include id/label/description in domain module: {path}")
            if aspect_id in seen_ids:
                raise ValueError(f"duplicate aspect ids in domain module '{path.stem}': {aspect_id}")
            seen_ids.add(aspect_id)
            aspects.append(
                RubricAspect(
                    id=aspect_id,
                    label=label,
                    description=description,
                    priority=priority,
                )
            )
        return aspects

    def _load_contract(self, ref: Path, *, path: Path) -> list[AcceptanceCheck]:
        raw = self._read_yaml(ref)
        checks = raw.get("checks", raw.get("acceptance_criteria"))
        if not isinstance(checks, list):
            raise ValueError(f"checks must be a list in domain module: {path}")
        return [self._build_check(item, path=path) for item in checks]

    def _build_check(self, item: Any, *, path: Path) -> AcceptanceCheck:
        if not isinstance(item, dict):
            raise ValueError(f"check item must be a mapping in domain module: {path}")
        payload = dict(item)
        payload["requires"] = payload.pop("requires", payload.pop("required_outputs", []))
        return AcceptanceCheck.model_validate(payload)

    def _parse_knowledge_md(
        self, text: str
    ) -> tuple[str, list[RubricAspect], str, list[AcceptanceCheck]]:
        sections = self._split_sections(text)
        if "persona" not in sections:
            raise ValueError("knowledge.md에 '## Persona' 섹션이 필요합니다.")
        if "aspects" not in sections:
            raise ValueError("knowledge.md에 '## Aspects' 섹션이 필요합니다.")
        persona = sections["persona"].strip()
        rubric = self._parse_aspects(sections["aspects"])
        contract = self._parse_checks(sections.get("checks", ""))
        format_spec = sections.get("format", "").strip()
        return persona, rubric, format_spec, contract

    def _split_sections(self, text: str) -> dict[str, str]:
        sections: dict[str, str] = {}
        matches = list(SECTION_HEADING.finditer(text))
        for index, match in enumerate(matches):
            name = match.group(1).strip().lower()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            if name in sections and sections[name]:
                sections[name] = f"{sections[name]}\n\n{body}".strip()
            else:
                sections[name] = body
        return sections

    def _parse_aspects(self, text: str) -> list[RubricAspect]:
        for line in text.splitlines():
            if not line.startswith("### "):
                continue
            match = ASPECT_HEADING.fullmatch(line.strip())
            priority = match.group(3).strip().lower() if match else ""
            if match is None or priority not in VALID_PRIORITIES:
                raise ValueError(
                    "aspect 형식이 올바르지 않습니다: "
                    f"'{line.strip()}'. 올바른 형식: {ASPECT_GUIDE}"
                )

        matches = list(ASPECT_HEADING.finditer(text))
        if not matches:
            raise ValueError(
                "'## Aspects' 섹션에 최소 1개의 aspect가 필요합니다. "
                f"형식: {ASPECT_GUIDE}"
            )

        aspects: list[RubricAspect] = []
        seen_ids: set[str] = set()
        for index, match in enumerate(matches):
            aspect_id = match.group(1).strip()
            if aspect_id in seen_ids:
                raise ValueError(f"aspect id '{aspect_id}'가 중복됩니다.")
            seen_ids.add(aspect_id)
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            description = text[match.end() : end].strip()
            aspects.append(
                RubricAspect(
                    id=aspect_id,
                    label=match.group(2).strip(),
                    description=description,
                    priority=match.group(3).strip().lower(),
                )
            )
        return aspects

    def _parse_checks(self, text: str) -> list[AcceptanceCheck]:
        checks: list[AcceptanceCheck] = []
        lines = text.splitlines()
        index = 0
        while index < len(lines):
            line = lines[index].strip()
            if not line or self._is_comment_line(line):
                index += 1
                continue
            item_match = CHECK_ITEM.fullmatch(line)
            if item_match is None:
                raise ValueError(
                    "check 형식이 올바르지 않습니다: "
                    f"'{line}'. 올바른 형식: - **check_id**: 설명"
                )
            check_id = item_match.group(1).strip()
            check_text = item_match.group(2).strip()
            index += 1
            while index < len(lines):
                requires_line = lines[index].strip()
                if not requires_line or self._is_comment_line(requires_line):
                    index += 1
                    continue
                break
            if index >= len(lines):
                raise ValueError(
                    f"check '{check_id}'의 requires 형식이 올바르지 않습니다. "
                    "올바른 형식:   → aspect_id"
                )
            requires_match = CHECK_REQUIRES.fullmatch(lines[index].strip())
            if requires_match is None:
                raise ValueError(
                    f"check '{check_id}'의 requires 형식이 올바르지 않습니다. "
                    "올바른 형식:   → aspect_id"
                )
            requires = [
                item.strip()
                for item in requires_match.group(1).split(",")
                if item.strip()
            ]
            checks.append(
                AcceptanceCheck(id=check_id, text=check_text, requires=requires)
            )
            index += 1
        return checks

    def _is_comment_line(self, line: str) -> bool:
        return line.startswith("<!--") and line.endswith("-->")

    def _ref(self, data: dict[str, Any], *names: str) -> str | None:
        for name in names:
            value = data.get(name)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    def _read_text(self, path: Path) -> str:
        if not path.is_file():
            raise FileNotFoundError(f"referenced domain file not found: {path}")
        return path.read_text(encoding="utf-8").strip()

    def _validate_contract_references(
        self,
        rubric: list[RubricAspect],
        contract: list[AcceptanceCheck],
        *,
        path: Path,
    ) -> None:
        aspect_ids = {aspect.id for aspect in rubric}
        for check in contract:
            for ref in check.requires:
                if ref not in aspect_ids:
                    valid_ids = ", ".join(sorted(aspect_ids))
                    raise ValueError(
                        f"check '{check.id}'의 참조 '{ref}'가 aspects에 없습니다. "
                        f"사용 가능: {valid_ids}"
                    )

    def _string_list(self, raw: Any, *, field_name: str, path: Path) -> list[str]:
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise ValueError(f"{field_name} must be a list in domain module: {path}")
        return list(dict.fromkeys(str(item).strip() for item in raw if str(item).strip()))

    def _ensure_no_cycles(self, modules: dict[str, DomainModule]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def walk(module_id: str) -> None:
            if module_id in visited:
                return
            if module_id in visiting:
                raise ValueError(f"cycle detected in domain depends_on: {module_id}")
            visiting.add(module_id)
            for dependency in modules[module_id].depends_on:
                if dependency not in modules:
                    raise ValueError(
                        f"unknown dependency '{dependency}' in domain module '{module_id}'"
                    )
                walk(dependency)
            visiting.remove(module_id)
            visited.add(module_id)

        for module_id in modules:
            walk(module_id)


    def _resolve_index_path(self, root: Path) -> Path:
        if (root / "index.yaml").is_file():
            return root / "index.yaml"
        legacy_knowledge_index = root / "knowledge" / "index.yaml"
        if legacy_knowledge_index.is_file():
            return legacy_knowledge_index
        if root == KNOWLEDGE_ROOT:
            return INDEX_PATH
        return root / "index.yaml"

    def _resolve_modules_root(self, root: Path) -> Path:
        modules_root = root / "modules"
        if modules_root.is_dir():
            return modules_root
        legacy_modules_root = root / "knowledge" / "modules"
        if legacy_modules_root.is_dir():
            return legacy_modules_root
        if root == KNOWLEDGE_ROOT:
            return MODULES_ROOT
        return root
