from __future__ import annotations

import unittest

from server.services.valuator_snapshot import project_snapshot_plan


class SnapshotPlanProjectionTests(unittest.TestCase):
    def test_projects_analysis_units_and_requirements_into_snapshot_shape(self) -> None:
        raw_plan = {
            "query": "종목 추천 좀",
            "analysis": {
                "units": [
                    {
                        "id": "u_screening",
                        "objective": "Find candidates",
                        "retrieval_query": "candidate screening",
                        "domain_ids": ["balance_sheet"],
                        "entity_ids": [],
                        "time_scope": "Last 3 years",
                    },
                    {
                        "id": "u_valuation",
                        "objective": "Compare intrinsic value",
                        "retrieval_query": "dcf comparison",
                        "domain_ids": ["dcf"],
                        "entity_ids": [],
                        "time_scope": "Current",
                    },
                ],
                "requirements": [
                    {
                        "id": "R-001",
                        "acceptance": "Return explicit picks.",
                        "unit_ids": [0, "1"],
                        "domain_ids": ["dcf", "balance_sheet"],
                        "entity_ids": [],
                        "provenance": "Derived from query.",
                        "required": True,
                        "requirement_type": "recommendation",
                    }
                ],
                "rationale": "Recommendation query.",
            },
            "tasks": [{"id": "T-LEAF-1", "task_type": "leaf", "query_unit_ids": [0]}],
            "root_task_id": "T-ROOT",
        }

        payload = project_snapshot_plan(raw_plan)

        self.assertEqual(len(payload["query_units"]), 2)
        self.assertEqual(payload["query_units"][0]["objective"], "Find candidates")
        self.assertEqual(payload["tasks"], raw_plan["tasks"])
        self.assertEqual(payload["root_task_id"], "T-ROOT")
        self.assertEqual(payload["contract"]["rationale"], "Recommendation query.")
        self.assertEqual(payload["contract"]["items"][0]["id"], "R-001")
        self.assertEqual(payload["contract"]["items"][0]["unit_id"], 0)
        self.assertEqual(payload["contract"]["items"][0]["unit_ids"], [0, 1])
        self.assertEqual(
            payload["contract"]["items"][0]["requirement_type"], "recommendation"
        )

    def test_preserves_legacy_snapshot_plan_shape(self) -> None:
        raw_plan = {
            "query_units": ["legacy unit"],
            "contract": {"items": [{"id": "R-LEGACY", "unit_id": 0, "unit_ids": [0]}]},
            "tasks": [{"id": "T-LEAF-1"}],
            "root_task_id": "T-ROOT",
            "analysis": {
                "units": [{"id": "u_should_not_override"}],
                "requirements": [{"id": "R-NEW"}],
            },
        }

        payload = project_snapshot_plan(raw_plan)

        self.assertEqual(payload["query_units"], ["legacy unit"])
        self.assertEqual(payload["contract"], raw_plan["contract"])
        self.assertEqual(payload["tasks"], raw_plan["tasks"])
        self.assertEqual(payload["root_task_id"], "T-ROOT")


if __name__ == "__main__":
    unittest.main()
