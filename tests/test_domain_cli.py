from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from textwrap import dedent

from valuator.domain import DomainLoader
from valuator.domain.scaffold import scaffold_module
from valuator.domain.validate import validate_modules


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")


class DomainCliTests(unittest.TestCase):
    def test_validate_reports_successful_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(
                root / "index.yaml",
                """
                schema_version: 1
                modules:
                  - ceo
                """,
            )
            _write(
                root / "modules" / "ceo" / "module.yaml",
                """
                id: ceo
                name: CEO
                description: Leadership module.
                depends_on: []
                """,
            )
            _write(
                root / "modules" / "ceo" / "knowledge.md",
                """
                ## Persona
                Long-term leadership analyst.

                ## Aspects
                ### integrity — Integrity [HIGH]
                Transparency and honesty.

                ### governance — Governance [MEDIUM]
                Board quality.

                ## Checks
                - **leadership_defined**: Leadership conclusion is explicit.
                  → integrity
                """,
            )

            success_lines, error_lines = validate_modules(root=root)

        self.assertEqual(error_lines, [])
        self.assertEqual(len(success_lines), 1)
        self.assertIn("✓ ceo", success_lines[0])
        self.assertIn("2 aspects (1 high, 1 medium)", success_lines[0])
        self.assertIn("1 checks", success_lines[0])

    def test_validate_reports_knowledge_reference_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(
                root / "index.yaml",
                """
                schema_version: 1
                modules:
                  - ceo
                """,
            )
            _write(
                root / "modules" / "ceo" / "module.yaml",
                """
                id: ceo
                name: CEO
                description: Leadership module.
                depends_on: []
                """,
            )
            _write(
                root / "modules" / "ceo" / "knowledge.md",
                """
                ## Persona
                Long-term leadership analyst.

                ## Aspects
                ### integrity — Integrity [HIGH]
                Transparency and honesty.

                ## Checks
                - **leadership_defined**: Leadership conclusion is explicit.
                  → intgrity
                """,
            )

            success_lines, error_lines = validate_modules(root=root)

        self.assertEqual(success_lines, [])
        self.assertEqual(len(error_lines), 1)
        self.assertIn("✗ ceo", error_lines[0])
        self.assertIn("knowledge.md", error_lines[0])
        self.assertIn("intgrity", error_lines[0])

    def test_scaffold_creates_module_and_updates_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(
                root / "index.yaml",
                """
                schema_version: 1
                modules: []
                """,
            )

            created_paths = scaffold_module("esg", root=root)
            _, modules = DomainLoader(root=root).load()

            self.assertEqual([path.name for path in created_paths], ["module.yaml", "knowledge.md"])
            self.assertIn("esg", modules)
            self.assertIn("## Persona", created_paths[1].read_text(encoding="utf-8"))
            self.assertIn("- esg", (root / "index.yaml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
