from __future__ import annotations

from pathlib import Path
import sys

from .loader import DomainLoader
from .types import DomainModule


def validate_modules(
    root: Path | None = None,
) -> tuple[list[str], list[str]]:
    loader = DomainLoader(root=root)
    index = loader._read_yaml(loader._index_path)
    module_ids = list(index.get("modules") or [])
    width = max((len(str(module_id)) for module_id in module_ids), default=0)
    width = max(width, 12)

    modules: dict[str, DomainModule] = {}
    success_lines: list[str] = []
    error_lines: list[str] = []

    for raw_module_id in module_ids:
        module_id = str(raw_module_id).strip()
        source_name = "module.yaml"
        try:
            module_path = loader._module_path(module_id)
            source_name = _source_name(loader, module_path)
            module = loader._build_module(loader._read_yaml(module_path), path=module_path)
            if module.id != module_id:
                raise ValueError(
                    f"domain module id mismatch: file={module_id}.yaml id={module.id}"
                )
        except Exception as exc:
            error_lines.append(
                f"✗ {module_id.ljust(width)}  {source_name}\n"
                f"  {exc}"
            )
            continue

        modules[module_id] = module
        success_lines.append(_format_success(module_id, module, width=width))

    if not error_lines:
        try:
            loader._ensure_no_cycles(modules)
        except Exception as exc:
            error_lines.append(f"✗ dependencies\n  {exc}")

    return success_lines, error_lines


def main(argv: list[str] | None = None) -> int:
    del argv
    try:
        success_lines, error_lines = validate_modules()
    except Exception as exc:
        print(f"✗ validate\n  {exc}")
        return 1

    for line in success_lines:
        print(line)
    for line in error_lines:
        print(line)

    if error_lines:
        return 1

    print()
    print("모든 모듈 로드 성공. 교차 참조 검증 통과.")
    return 0


def _format_success(module_id: str, module: DomainModule, *, width: int) -> str:
    counts = {"high": 0, "medium": 0, "low": 0}
    for aspect in module.rubric:
        if aspect.priority in counts:
            counts[aspect.priority] += 1
    priority_text = ", ".join(
        f"{counts[priority]} {priority}"
        for priority in ("high", "medium", "low")
        if counts[priority]
    )
    return (
        f"✓ {module_id.ljust(width)} — "
        f"{len(module.rubric)} aspects ({priority_text}), "
        f"{len(module.contract)} checks"
    )


def _source_name(loader: DomainLoader, module_path: Path) -> str:
    data = loader._read_yaml(module_path)
    knowledge_ref = loader._ref(data, "knowledge") or "knowledge.md"
    knowledge_path = module_path.parent / knowledge_ref
    if knowledge_path.is_file():
        return knowledge_path.name
    return module_path.name


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
