from __future__ import annotations

from pathlib import Path

import yaml

from .types import DomainIndex, DomainModule, DomainReportRequirement, DomainTask


class DomainLoader:
    """Load and validate domain modules from YAML files.

    This is a boundary for YAML configuration: all schema checks happen here.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(__file__).resolve().parent

    def load(self) -> tuple[DomainIndex, dict[str, DomainModule]]:
        """Load index and all referenced modules."""
        index_path = self._root / "index.yaml"
        index_data = self._read_yaml(index_path)
        index = DomainIndex.model_validate(index_data)

        modules: dict[str, DomainModule] = {}
        for module_id in index.modules:
            module_path = self._root / f"{module_id}.yaml"
            module_data = self._read_yaml(module_path)
            module = self._build_module(module_data, path=module_path)
            if module.id != module_id:
                raise ValueError(
                    f"domain module id mismatch: file={module_id}.yaml id={module.id}"
                )
            modules[module_id] = module

        self._ensure_no_cycles(modules)
        return index, modules

    def _read_yaml(self, path: Path) -> dict:
        if not path.is_file():
            raise FileNotFoundError(f"domain config not found: {path}")
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise ValueError(f"domain YAML root must be a mapping: {path}")
        return data

    def _build_module(self, data: dict, *, path: Path) -> DomainModule:
        report_contract_raw = data.get("report_contract") or []
        if not isinstance(report_contract_raw, list):
            raise ValueError(
                f"report_contract must be a list in domain module: {path}"
            )
        report_contract = [
            DomainReportRequirement(text=str(item).strip())
            for item in report_contract_raw
            if str(item).strip()
        ]

        tasks_raw = data.get("tasks") or []
        if not isinstance(tasks_raw, list):
            raise ValueError(f"tasks must be a list in domain module: {path}")
        tasks = []
        for t in tasks_raw:
            if isinstance(t, dict) and "id" in t:
                tasks.append(
                    DomainTask(
                        id=str(t["id"]).strip(),
                        name=str(t.get("name") or "").strip(),
                    )
                )

        prompt_fragment = str(data.get("prompt_fragment") or "").strip()
        prompt_file = data.get("prompt_file")
        if prompt_file and not prompt_fragment:
            prompt_path = (self._root / str(prompt_file)).resolve()
            if not prompt_path.is_file():
                raise FileNotFoundError(
                    f"prompt_file not found for domain module {path}: {prompt_path}"
                )
            prompt_fragment = prompt_path.read_text(encoding="utf-8").strip()

        payload = dict(data)
        payload["report_contract"] = report_contract
        payload["tasks"] = tasks
        payload["prompt_fragment"] = prompt_fragment
        return DomainModule.model_validate(payload)

    def _ensure_no_cycles(self, modules: dict[str, DomainModule]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def _dfs(node: str) -> None:
            if node in visited:
                return
            if node in visiting:
                raise ValueError(f"cycle detected in domain depends_on: {node}")
            visiting.add(node)
            module = modules.get(node)
            if module is not None:
                for dep in module.depends_on:
                    if dep not in modules:
                        raise ValueError(
                            f"unknown dependency '{dep}' in domain module '{node}'"
                        )
                    _dfs(dep)
            visiting.remove(node)
            visited.add(node)

        for module_id in modules:
            _dfs(module_id)

