from __future__ import annotations

from valuator.core.shared_state import SharedState


def test_view_for_root_sees_all_facts() -> None:
    shared = SharedState()
    shared.publish("a", 1, "root.0", query_unit_ids=(0,))
    shared.publish("b", 2, "root.2.0", query_unit_ids=(1,))
    view = shared.view_for(task_id="root", query_unit_ids=[])
    assert set(view.facts.keys()) == {"a", "b"}


def test_view_for_excludes_other_branch_without_shared_query_unit() -> None:
    shared = SharedState()
    shared.publish("peer", "x", "root.2.0", query_unit_ids=(1,))
    shared.publish("local", "y", "root.0.1", query_unit_ids=(0,))
    view = shared.view_for(task_id="root.0.1", query_unit_ids=[2])
    assert "local" in view.facts
    assert "peer" not in view.facts


def test_view_for_includes_fact_from_other_branch_with_query_unit_overlap() -> None:
    shared = SharedState()
    shared.publish("shared_metric", 42, "root.2.0", query_unit_ids=(0, 2))
    view = shared.view_for(task_id="root.0.1", query_unit_ids=[0])
    assert view.facts["shared_metric"].value == 42


def test_view_for_includes_global_facts_always() -> None:
    shared = SharedState()
    shared.publish("global_k", "v", "root.9.9", query_unit_ids=())
    view = shared.view_for(task_id="root.0.1", query_unit_ids=[99])
    assert view.facts["global_k"].value == "v"


def test_view_for_includes_same_subtree_sibling_facts() -> None:
    shared = SharedState()
    shared.publish("sib", 1, "root.0.2", query_unit_ids=(0,))
    view = shared.view_for(task_id="root.0.1", query_unit_ids=[1])
    assert "sib" in view.facts
