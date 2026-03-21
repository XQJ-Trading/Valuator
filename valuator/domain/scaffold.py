from __future__ import annotations

from pathlib import Path
import re
import sys

import yaml

from .knowledge import KNOWLEDGE_ROOT
from .loader import DomainLoader

MODULE_ID = re.compile(r"^[a-z][a-z0-9_]*$")
KNOWLEDGE_TEMPLATE = """<!-- 이 파일은 AI 분석가에게 보내는 가이드 문서입니다. -->
<!-- 각 섹션을 편집하여 분석 방식을 설정하세요. -->

## Persona

당신은 기업 가치 분석 전문가입니다.
[여기에 분석가의 역할과 관점을 작성하세요]

## Aspects

<!-- 분석 관점을 추가하세요. 형식: ### id — 라벨 [HIGH/MEDIUM/LOW] -->

### example_aspect — 예시 관점 [HIGH]
이 관점에서 분석할 내용을 설명합니다.

## Checks

<!-- (선택) 출력에 반드시 포함되어야 할 품질 기준. 없으면 이 섹션을 삭제하세요. -->

- **example_check**: 예시 품질 기준 설명
  → example_aspect

## Format

<!-- (선택) 출력 형식 규칙. 없으면 이 섹션을 삭제하세요. -->

- 한글 마크다운으로 작성한다.
- 각 aspect는 `### [ASPECT:{aspect_id}] {label}` 헤더로 작성한다.
"""


def scaffold_module(module_id: str, *, root: Path | None = None) -> list[Path]:
    module_id = module_id.strip()
    if not MODULE_ID.fullmatch(module_id):
        raise ValueError("module id는 영문 소문자와 밑줄만 사용할 수 있습니다.")

    base_root = root or KNOWLEDGE_ROOT
    modules_root = base_root / "modules"
    module_dir = modules_root / module_id
    module_yaml = module_dir / "module.yaml"
    knowledge_md = module_dir / "knowledge.md"
    index_path = base_root / "index.yaml"

    if module_dir.exists():
        raise FileExistsError(f"이미 존재하는 모듈입니다: {module_dir}")

    modules_root.mkdir(parents=True, exist_ok=True)

    previous_index_text = index_path.read_text(encoding="utf-8") if index_path.is_file() else None
    index_data = yaml.safe_load(previous_index_text) if previous_index_text else {}
    if index_data is None:
        index_data = {}
    if not isinstance(index_data, dict):
        raise ValueError(f"index.yaml 루트는 mapping이어야 합니다: {index_path}")

    modules = list(index_data.get("modules") or [])
    if module_id in {str(item).strip() for item in modules}:
        raise ValueError(f"index.yaml에 이미 '{module_id}'가 등록되어 있습니다.")

    module_dir.mkdir(parents=True, exist_ok=False)
    created_paths = [module_yaml, knowledge_md]
    try:
        module_yaml.write_text(
            "\n".join(
                [
                    f"id: {module_id}",
                    f"name: {module_id}",
                    "description: ''",
                    "depends_on: []",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        knowledge_md.write_text(KNOWLEDGE_TEMPLATE, encoding="utf-8")

        index_data.setdefault("schema_version", 1)
        index_data["modules"] = [*modules, module_id]
        index_path.write_text(
            yaml.safe_dump(index_data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        DomainLoader(root=base_root).load()
    except Exception:
        for created_path in reversed(created_paths):
            if created_path.exists():
                created_path.unlink()
        if module_dir.exists():
            module_dir.rmdir()
        if previous_index_text is None:
            if index_path.exists():
                index_path.unlink()
        else:
            index_path.write_text(previous_index_text, encoding="utf-8")
        raise

    return created_paths


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if len(args) != 1:
        print("사용법: python -m valuator.domain.scaffold <module_id>")
        return 1

    try:
        created_paths = scaffold_module(args[0])
    except Exception as exc:
        print(f"✗ scaffold\n  {exc}")
        return 1

    print("생성됨:")
    for path in created_paths:
        print(f"  {path.relative_to(KNOWLEDGE_ROOT)}")
    print()
    print(f"index.yaml에 '{args[0].strip()}' 추가됨.")
    print("검증 통과 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
