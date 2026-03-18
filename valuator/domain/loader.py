from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .knowledge import INDEX_PATH, KNOWLEDGE_ROOT, MODULES_ROOT
from .types import AcceptanceCheck, DomainIndex, DomainModule, RubricAspect


class DomainLoader:
    """Load and validate domain modules from YAML files."""

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
        persona_ref = self._ref(data, "persona", "persona_file") or "persona.md"
        rubric_ref = self._ref(data, "rubric", "rubric_file") or "rubric.yaml"
        format_ref = self._ref(data, "format", "format_file") or "format.md"
        contract_ref = self._ref(data, "contract", "contract_file") or "contract.yaml"
        return DomainModule(
            id=str(data["id"]).strip(),
            name=str(data["name"]).strip(),
            description=str(data.get("description") or "").strip(),
            persona=self._read_text(base_dir / persona_ref),
            rubric=self._load_rubric(base_dir / rubric_ref, path=path),
            format_spec=self._read_text(base_dir / format_ref),
            contract=self._load_contract(base_dir / contract_ref, path=path),
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
