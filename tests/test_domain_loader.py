from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from textwrap import dedent

from valuator.domain import DomainLoader


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")


class DomainLoaderTests(unittest.TestCase):
    def _write_root(self, root: Path, modules: dict[str, dict[str, str]]) -> None:
        module_ids = list(modules)
        _write(
            root / "index.yaml",
            "schema_version: 1\nmodules:\n"
            + "".join(f"  - {module_id}\n" for module_id in module_ids),
        )
        for module_id, files in modules.items():
            module_dir = root / "modules" / module_id
            for name, content in files.items():
                _write(module_dir / name, content)

    def _load(self, modules: dict[str, dict[str, str]]):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_root(root, modules)
            return DomainLoader(root=root).load()

    def test_loader_reads_knowledge_markdown_sections(self) -> None:
        _, modules = self._load(
            {
                "ceo": {
                    "knowledge.md": """
                    ## Format

                    - Use aspect headers.

                    ## Persona

                    Long-term leadership analyst.

                    ## Notes

                    Ignore this section.

                    ## Checks

                    - **leadership_defined**: Leadership conclusion is explicit.
                      → integrity

                    ## Aspects

                    ### integrity — Integrity [HIGH]
                    Transparency and honesty.

                    ### governance - Governance [medium]
                    Board quality.
                    """,
                    "module.yaml": """
                    id: ceo
                    name: CEO
                    description: Leadership module.
                    depends_on: []
                    """,
                }
            }
        )

        module = modules["ceo"]
        self.assertEqual(module.persona, "Long-term leadership analyst.")
        self.assertEqual(module.format_spec, "- Use aspect headers.")
        self.assertEqual([aspect.id for aspect in module.rubric], ["integrity", "governance"])
        self.assertEqual([aspect.priority for aspect in module.rubric], ["high", "medium"])
        self.assertEqual(module.contract[0].requires, ["integrity"])

    def test_loader_supports_minimal_knowledge_markdown(self) -> None:
        _, modules = self._load(
            {
                "simple": {
                    "knowledge.md": """
                    ## Persona
                    기업 가치 분석가입니다.

                    ## Aspects
                    ### revenue — 매출 분석 [HIGH]
                    매출 추이와 성장 동인
                    """,
                    "module.yaml": """
                    id: simple
                    name: Simple
                    description: Minimal module.
                    depends_on: []
                    """,
                }
            }
        )

        module = modules["simple"]
        self.assertEqual(module.persona, "기업 가치 분석가입니다.")
        self.assertEqual(module.format_spec, "")
        self.assertEqual(module.contract, [])
        self.assertEqual([aspect.id for aspect in module.rubric], ["revenue"])

    def test_loader_accepts_custom_knowledge_reference(self) -> None:
        _, modules = self._load(
            {
                "custom": {
                    "guide.md": """
                    ## Persona
                    Persona

                    ## Aspects
                    ### quality — Quality [HIGH]
                    Quality aspect.
                    """,
                    "module.yaml": """
                    id: custom
                    name: Custom
                    description: Custom knowledge path.
                    knowledge: guide.md
                    depends_on: []
                    """,
                }
            }
        )

        self.assertEqual(modules["custom"].persona, "Persona")

    def test_loader_reads_legacy_split_files(self) -> None:
        _, modules = self._load(
            {
                "ceo": {
                    "persona.md": "Long-term leadership analyst.",
                    "rubric.yaml": """
                    aspects:
                      - id: integrity
                        label: Integrity
                        description: Transparency and honesty.
                        priority: high
                      - id: governance
                        label: Governance
                        description: Board quality.
                        priority: medium
                    """,
                    "format.md": "Use aspect headers.",
                    "contract.yaml": """
                    checks:
                      - id: leadership_defined
                        text: Leadership conclusion is explicit.
                        requires:
                          - integrity
                    """,
                    "module.yaml": """
                    id: ceo
                    name: CEO
                    description: Leadership module.
                    persona: persona.md
                    rubric: rubric.yaml
                    format: format.md
                    contract: contract.yaml
                    depends_on: []
                    """,
                }
            }
        )

        module = modules["ceo"]
        self.assertEqual(module.persona, "Long-term leadership analyst.")
        self.assertEqual(module.format_spec, "Use aspect headers.")
        self.assertEqual([aspect.id for aspect in module.rubric], ["integrity", "governance"])
        self.assertEqual(module.contract[0].requires, ["integrity"])

    def test_loader_accepts_acceptance_criteria_alias(self) -> None:
        _, modules = self._load(
            {
                "legacy_contract": {
                    "persona.md": "Persona",
                    "rubric.yaml": """
                    aspects:
                      - id: quality
                        label: Quality
                        description: Quality aspect.
                    """,
                    "format.md": "Format",
                    "acceptance.yaml": """
                    acceptance_criteria:
                      - id: quality_defined
                        text: Quality is covered.
                        required_outputs:
                          - quality
                    """,
                    "module.yaml": """
                    id: legacy_contract
                    name: Legacy Contract
                    description: Uses acceptance alias.
                    contract_file: acceptance.yaml
                    depends_on: []
                    """,
                }
            }
        )

        self.assertEqual(modules["legacy_contract"].contract[0].requires, ["quality"])

    def test_loader_requires_persona_section(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "knowledge\\.md에 '## Persona' 섹션이 필요합니다\\.",
        ):
            self._load(
                {
                    "broken": {
                        "knowledge.md": """
                        ## Aspects
                        ### integrity — Integrity [HIGH]
                        Description
                        """,
                        "module.yaml": """
                        id: broken
                        name: Broken
                        description: Broken module.
                        depends_on: []
                        """,
                    }
                }
            )

    def test_loader_requires_aspects_section(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "knowledge\\.md에 '## Aspects' 섹션이 필요합니다\\.",
        ):
            self._load(
                {
                    "broken": {
                        "knowledge.md": """
                        ## Persona
                        Persona
                        """,
                        "module.yaml": """
                        id: broken
                        name: Broken
                        description: Broken module.
                        depends_on: []
                        """,
                    }
                }
            )

    def test_loader_requires_at_least_one_aspect(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "'## Aspects' 섹션에 최소 1개의 aspect가 필요합니다\\.",
        ):
            self._load(
                {
                    "broken": {
                        "knowledge.md": """
                        ## Persona
                        Persona

                        ## Aspects
                        """,
                        "module.yaml": """
                        id: broken
                        name: Broken
                        description: Broken module.
                        depends_on: []
                        """,
                    }
                }
            )

    def test_loader_rejects_invalid_aspect_heading(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "aspect 형식이 올바르지 않습니다: '### integrity : Integrity \\[HIGH\\]'",
        ):
            self._load(
                {
                    "broken": {
                        "knowledge.md": """
                        ## Persona
                        Persona

                        ## Aspects
                        ### integrity : Integrity [HIGH]
                        Description
                        """,
                        "module.yaml": """
                        id: broken
                        name: Broken
                        description: Broken module.
                        depends_on: []
                        """,
                    }
                }
            )

    def test_loader_rejects_duplicate_aspect_ids_in_knowledge_markdown(self) -> None:
        with self.assertRaisesRegex(ValueError, "aspect id 'integrity'가 중복됩니다\\."):
            self._load(
                {
                    "dup_aspects": {
                        "knowledge.md": """
                        ## Persona
                        Persona

                        ## Aspects
                        ### integrity — First [HIGH]
                        First description.

                        ### integrity — Second [LOW]
                        Second description.
                        """,
                        "module.yaml": """
                        id: dup_aspects
                        name: Duplicate Aspects
                        description: Invalid module.
                        depends_on: []
                        """,
                    }
                }
            )

    def test_loader_rejects_invalid_check_references_in_knowledge_markdown(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "check 'leadership_defined'의 참조 'intgrity'가 aspects에 없습니다\\. 사용 가능: integrity",
        ):
            self._load(
                {
                    "broken": {
                        "knowledge.md": """
                        ## Persona
                        Persona

                        ## Aspects
                        ### integrity — Integrity [HIGH]
                        Description

                        ## Checks
                        - **leadership_defined**: Leadership conclusion is explicit.
                          → intgrity
                        """,
                        "module.yaml": """
                        id: broken
                        name: Broken
                        description: Broken module.
                        depends_on: []
                        """,
                    }
                }
            )

    def test_loader_rejects_invalid_check_references_in_legacy_yaml(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "check 'quality_defined'의 참조 'missing'가 aspects에 없습니다\\. 사용 가능: quality",
        ):
            self._load(
                {
                    "broken": {
                        "persona.md": "Persona",
                        "rubric.yaml": """
                        aspects:
                          - id: quality
                            label: Quality
                            description: Quality aspect.
                        """,
                        "format.md": "Format",
                        "contract.yaml": """
                        checks:
                          - id: quality_defined
                            text: Quality is covered.
                            requires:
                              - missing
                        """,
                        "module.yaml": """
                        id: broken
                        name: Broken
                        description: Broken module.
                        depends_on: []
                        """,
                    }
                }
            )

    def test_loader_preserves_module_dependencies(self) -> None:
        _, modules = self._load(
            {
                "upstream": {
                    "knowledge.md": """
                    ## Persona
                    Upstream

                    ## Aspects
                    ### upstream_signal — Upstream signal [HIGH]
                    Upstream detail.
                    """,
                    "module.yaml": """
                    id: upstream
                    name: Upstream
                    description: Upstream module.
                    depends_on: []
                    """,
                },
                "downstream": {
                    "knowledge.md": """
                    ## Persona
                    Downstream

                    ## Aspects
                    ### downstream_signal — Downstream signal [HIGH]
                    Downstream detail.
                    """,
                    "module.yaml": """
                    id: downstream
                    name: Downstream
                    description: Downstream module.
                    depends_on:
                      - upstream
                    """,
                },
            }
        )

        self.assertEqual(modules["downstream"].depends_on, ["upstream"])

    def test_loader_rejects_dependency_cycles(self) -> None:
        with self.assertRaisesRegex(ValueError, "cycle detected"):
            self._load(
                {
                    "a": {
                        "knowledge.md": """
                        ## Persona
                        A

                        ## Aspects
                        ### aspect_a — A [HIGH]
                        A
                        """,
                        "module.yaml": """
                        id: a
                        name: A
                        description: A
                        depends_on:
                          - b
                        """,
                    },
                    "b": {
                        "knowledge.md": """
                        ## Persona
                        B

                        ## Aspects
                        ### aspect_b — B [HIGH]
                        B
                        """,
                        "module.yaml": """
                        id: b
                        name: B
                        description: B
                        depends_on:
                          - a
                        """,
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
