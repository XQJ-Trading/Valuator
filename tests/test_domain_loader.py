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

    def test_loader_reads_persona_rubric_format_and_contract(self) -> None:
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
        self.assertEqual(module.rubric[0].priority, "high")
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

    def test_loader_preserves_module_dependencies(self) -> None:
        _, modules = self._load(
            {
                "upstream": {
                    "persona.md": "Upstream",
                    "rubric.yaml": """
                    aspects:
                      - id: upstream_signal
                        label: Upstream signal
                        description: Upstream detail.
                    """,
                    "format.md": "Format",
                    "contract.yaml": "checks: []",
                    "module.yaml": """
                    id: upstream
                    name: Upstream
                    description: Upstream module.
                    depends_on: []
                    """,
                },
                "downstream": {
                    "persona.md": "Downstream",
                    "rubric.yaml": """
                    aspects:
                      - id: downstream_signal
                        label: Downstream signal
                        description: Downstream detail.
                    """,
                    "format.md": "Format",
                    "contract.yaml": "checks: []",
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

    def test_loader_rejects_duplicate_aspect_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate aspect ids"):
            self._load(
                {
                    "dup_aspects": {
                        "persona.md": "Persona",
                        "rubric.yaml": """
                        aspects:
                          - id: repeated
                            label: First
                            description: First description.
                          - id: repeated
                            label: Second
                            description: Second description.
                        """,
                        "format.md": "Format",
                        "contract.yaml": "checks: []",
                        "module.yaml": """
                        id: dup_aspects
                        name: Duplicate Aspects
                        description: Invalid module.
                        depends_on: []
                        """,
                    }
                }
            )

    def test_loader_rejects_dependency_cycles(self) -> None:
        with self.assertRaisesRegex(ValueError, "cycle detected"):
            self._load(
                {
                    "a": {
                        "persona.md": "A",
                        "rubric.yaml": """
                        aspects:
                          - id: aspect_a
                            label: A
                            description: A
                        """,
                        "format.md": "Format",
                        "contract.yaml": "checks: []",
                        "module.yaml": """
                        id: a
                        name: A
                        description: A
                        depends_on:
                          - b
                        """,
                    },
                    "b": {
                        "persona.md": "B",
                        "rubric.yaml": """
                        aspects:
                          - id: aspect_b
                            label: B
                            description: B
                        """,
                        "format.md": "Format",
                        "contract.yaml": "checks: []",
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
