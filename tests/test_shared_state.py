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


def test_view_for_include_fact_keys() -> None:
    shared = SharedState()
    shared.publish("dup", 1, "root.0", query_unit_ids=(0,))
    shared.publish("keep", 2, "root.1", query_unit_ids=(0,))
    view = shared.view_for(
        task_id="root.0",
        query_unit_ids=[0],
        include_fact_keys=frozenset({"keep"}),
    )
    assert "dup" not in view.facts
    assert view.facts["keep"].value == 2


def test_view_for_root_respects_include_fact_keys() -> None:
    shared = SharedState()
    shared.publish("a", 1, "root.0", query_unit_ids=(0,))
    shared.publish("b", 2, "root.1", query_unit_ids=(1,))
    view = shared.view_for(
        task_id="root",
        query_unit_ids=[],
        include_fact_keys=frozenset({"b"}),
    )
    assert set(view.facts.keys()) == {"b"}


def test_relevant_fact_keys_for_matches_unfiltered_view() -> None:
    shared = SharedState()
    shared.publish("a", 1, "root.0", query_unit_ids=(0,))
    shared.publish("b", 2, "root.2.0", query_unit_ids=(1,))
    keys = shared.relevant_fact_keys_for(task_id="root.0", query_unit_ids=[0])
    view = shared.view_for(task_id="root.0", query_unit_ids=[0])
    assert keys == frozenset(view.facts.keys())


def test_publish_deep_merges_nested_dict_values() -> None:
    shared = SharedState()
    shared.publish(
        "Acme",
        {"revenue": {"2023": "100B KRW"}},
        "root.0",
        query_unit_ids=(0,),
    )
    conflict = shared.publish(
        "Acme",
        {"revenue": {"2024": "110B KRW"}, "ebitda": {"2023": "10B KRW"}},
        "root.1",
        query_unit_ids=(1,),
    )
    assert conflict is None
    fact = shared.view().facts["Acme"]
    assert fact.value == {
        "revenue": {"2023": "100B KRW", "2024": "110B KRW"},
        "ebitda": {"2023": "10B KRW"},
    }
    assert set(fact.query_unit_ids) == {0, 1}


def test_publish_scalar_conflict_unchanged() -> None:
    shared = SharedState()
    shared.publish("k", 1, "root.0")
    c = shared.publish("k", 2, "root.1")
    assert c is not None
    assert shared.view().facts["k"].value == 1
