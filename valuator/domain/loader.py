from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from .types import (
    DomainIndex,
    DomainModule,
    DomainReportRequirement,
    DomainTask,
    PipelineConfig,
)

_STAGE_REF_RE = re.compile(r"^\{stages\.(\w+)\}$")
_STAGE_REF_IN_TEXT_RE = re.compile(r"\{stages\.(\w+)\}")


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
            subdir_path = self._root / module_id / "module.yaml"
            flat_path = self._root / f"{module_id}.yaml"
            if subdir_path.is_file():
                module_path = subdir_path
            elif flat_path.is_file():
                module_path = flat_path
            else:
                raise FileNotFoundError(
                    f"domain module config not found for '{module_id}': {subdir_path}"
                )
            module_data = self._read_yaml(module_path)
            module = self._build_module(module_data, path=module_path)
            if module.id != module_id:
                raise ValueError(
                    f"domain module id mismatch: file={module_id}.yaml id={module.id}"
                )
            modules[module_id] = module

        self._ensure_no_cycles(modules)
        return index, modules

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise FileNotFoundError(f"domain config not found: {path}")
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise ValueError(f"domain YAML root must be a mapping: {path}")
        return data

    def _build_module(self, data: dict[str, Any], *, path: Path) -> DomainModule:
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
            prompt_path = (path.parent / str(prompt_file)).resolve()
            if not prompt_path.is_file():
                raise FileNotFoundError(
                    f"prompt_file not found for domain module {path}: {prompt_path}"
                )
            prompt_fragment = prompt_path.read_text(encoding="utf-8").strip()

        payload = dict(data)
        payload["report_contract"] = report_contract
        payload["tasks"] = tasks
        payload["prompt_fragment"] = prompt_fragment
        pipeline_path = path.parent / "pipeline.yaml"
        if pipeline_path.is_file():
            raw_pipeline = self._read_yaml(pipeline_path)
            payload["pipeline_config"] = self._build_pipeline_config(
                raw_pipeline,
                base_dir=path.parent,
            )
        return DomainModule.model_validate(payload)

    def _build_pipeline_config(
        self,
        raw: dict[str, Any],
        *,
        base_dir: Path,
    ) -> PipelineConfig:
        payload = dict(raw)
        stages_raw = payload.get("stages")
        if isinstance(stages_raw, list):
            payload["stages"] = [
                dict(stage) if isinstance(stage, dict) else stage
                for stage in stages_raw
            ]
        self._resolve_pipeline_files(payload, base_dir=base_dir)

        config = PipelineConfig.model_validate(payload)
        stage_ids = [stage.id for stage in config.stages]
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError(f"duplicate pipeline stage ids in {base_dir / 'pipeline.yaml'}")

        known_stage_ids = set(stage_ids)
        for stage in config.stages:
            for var_name, stage_id in stage.inject_vars.items():
                if stage_id not in known_stage_ids:
                    raise ValueError(
                        f"inject_vars '{var_name}' references unknown stage '{stage_id}'"
                    )
            self._validate_template_refs(stage.user_prompt, known_stage_ids)
            self._validate_template_refs(stage.system_prompt_content, known_stage_ids)

        for key, template in config.result_mapping.items():
            direct_ref = self._stage_ref_id(template)
            if direct_ref is not None and direct_ref not in known_stage_ids:
                raise ValueError(
                    f"result_mapping '{key}' references unknown stage '{direct_ref}'"
                )
            self._validate_template_refs(template, known_stage_ids)

        return config

    def _resolve_pipeline_files(
        self,
        raw: dict[str, Any],
        *,
        base_dir: Path,
    ) -> None:
        stages = raw.get("stages")
        if not isinstance(stages, list):
            return

        for stage in stages:
            if not isinstance(stage, dict):
                continue

            system_prompt_file = stage.pop("system_prompt_file", None)
            if system_prompt_file:
                stage["system_prompt_content"] = self._read_text(
                    base_dir / str(system_prompt_file)
                )

            output_schema_file = stage.pop("output_schema_file", None)
            if output_schema_file:
                schema_text = self._read_text(base_dir / str(output_schema_file))
                stage["output_schema_content"] = json.loads(schema_text)

            code_file = stage.pop("code_file", None)
            if code_file:
                stage["code_content"] = self._read_text(base_dir / str(code_file))

            inject_vars = stage.get("inject_vars")
            if isinstance(inject_vars, dict):
                stage["inject_vars"] = {
                    str(name): self._normalize_stage_ref(str(value))
                    for name, value in inject_vars.items()
                }

    def _read_text(self, path: Path) -> str:
        resolved = path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"referenced domain file not found: {resolved}")
        return resolved.read_text(encoding="utf-8").strip()

    def _normalize_stage_ref(self, value: str) -> str:
        stage_id = self._stage_ref_id(value)
        if stage_id is not None:
            return stage_id
        return value.strip()

    def _stage_ref_id(self, value: str) -> str | None:
        match = _STAGE_REF_RE.match(value.strip())
        if match is None:
            return None
        return match.group(1)

    def _validate_template_refs(
        self,
        template: str,
        stage_ids: set[str],
    ) -> None:
        for stage_id in _STAGE_REF_IN_TEXT_RE.findall(template):
            if stage_id not in stage_ids:
                raise ValueError(f"template references unknown stage '{stage_id}'")

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
