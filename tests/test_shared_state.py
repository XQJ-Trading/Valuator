from __future__ import annotations

from valuator.core.ontology import NumericValue, TextValue, parse_raw_fact
from valuator.core.shared_state import SharedState


def _fact(
    key: str,
    value: float | str,
    source: str,
    *,
    query_unit_ids: tuple[int, ...] = (),
    source_urls: tuple[str, ...] = (),
    source_tier: int | None = None,
):
    raw_value = value
    if source_urls or source_tier is not None:
        raw_value = {
            "value": value,
            "source_urls": source_urls,
        }
        if source_tier is not None:
            raw_value["source_tier"] = source_tier
    return parse_raw_fact(
        f"test:{key}",
        raw_value,
        source_task_id=source,
        query_unit_ids=query_unit_ids,
    )


def test_view_for_root_sees_all_facts() -> None:
    shared = SharedState()
    shared.publish(_fact("a", 1, "root.0", query_unit_ids=(0,)))
    shared.publish(_fact("b", 2, "root.2.0", query_unit_ids=(1,)))
    view = shared.view_for(task_id="root", query_unit_ids=[])
    assert len(view.facts) == 2


def test_view_for_excludes_other_branch_without_shared_query_unit() -> None:
    shared = SharedState()
    shared.publish(_fact("peer", "x", "root.2.0", query_unit_ids=(1,)))
    shared.publish(_fact("local", "y", "root.0.1", query_unit_ids=(0,)))
    view = shared.view_for(task_id="root.0.1", query_unit_ids=[2])
    local_keys = {f.address.property_key for f in view.facts.values()}
    assert "local" in local_keys
    # peer should not be visible (different branch, no query unit overlap)
    assert not any(
        f.source_task_id == "root.2.0" and f.address.property_key == "peer"
        for f in view.facts.values()
    )


def test_view_for_includes_fact_from_other_branch_with_query_unit_overlap() -> None:
    shared = SharedState()
    f = _fact("shared_metric", 42, "root.2.0", query_unit_ids=(0, 2))
    shared.publish(f)
    view = shared.view_for(task_id="root.0.1", query_unit_ids=[0])
    assert len(view.facts) == 1
    fact = list(view.facts.values())[0]
    assert fact.value == NumericValue(amount=42.0)


def test_view_for_includes_global_facts_always() -> None:
    shared = SharedState()
    shared.publish(_fact("global_k", "v", "root.9.9", query_unit_ids=()))
    view = shared.view_for(task_id="root.0.1", query_unit_ids=[99])
    assert len(view.facts) == 1
    fact = list(view.facts.values())[0]
    assert fact.value == TextValue(text="v")


def test_view_for_include_fact_keys() -> None:
    shared = SharedState()
    f_dup = _fact("dup", 1, "root.0", query_unit_ids=(0,))
    f_keep = _fact("keep", 2, "root.1", query_unit_ids=(0,))
    shared.publish(f_dup)
    shared.publish(f_keep)
    view = shared.view_for(
        task_id="root.0",
        query_unit_ids=[0],
        include_fact_keys=frozenset({f_keep.key}),
    )
    assert f_dup.key not in view.facts
    assert f_keep.key in view.facts


def test_view_for_root_respects_include_fact_keys() -> None:
    shared = SharedState()
    fa = _fact("a", 1, "root.0", query_unit_ids=(0,))
    fb = _fact("b", 2, "root.1", query_unit_ids=(1,))
    shared.publish(fa)
    shared.publish(fb)
    view = shared.view_for(
        task_id="root",
        query_unit_ids=[],
        include_fact_keys=frozenset({fb.key}),
    )
    assert set(view.facts.keys()) == {fb.key}


def test_relevant_fact_keys_for_matches_unfiltered_view() -> None:
    shared = SharedState()
    shared.publish(_fact("a", 1, "root.0", query_unit_ids=(0,)))
    shared.publish(_fact("b", 2, "root.2.0", query_unit_ids=(1,)))
    keys = shared.relevant_fact_keys_for(task_id="root.0", query_unit_ids=[0])
    view = shared.view_for(task_id="root.0", query_unit_ids=[0])
    assert keys == frozenset(view.facts.keys())


def test_publish_conflict_on_different_values() -> None:
    shared = SharedState()
    shared.publish(_fact("k", 1, "root.0"))
    c = shared.publish(_fact("k", 2, "root.1"))
    assert c is not None
    # original value preserved
    fact = list(shared.view().facts.values())[0]
    assert fact.value == NumericValue(amount=1.0)


def test_publish_same_value_no_conflict() -> None:
    shared = SharedState()
    shared.publish(_fact("k", 1, "root.0"))
    c = shared.publish(_fact("k", 1, "root.1"))
    assert c is None


def test_publish_prefers_higher_source_tier() -> None:
    shared = SharedState()
    shared.publish(
        _fact(
            "k",
            1,
            "root.0",
            source_urls=("https://www.reuters.com/markets/test",),
        )
    )
    c = shared.publish(
        _fact(
            "k",
            2,
            "root.1",
            source_urls=("https://dart.fss.or.kr/dsaf001/main.do",),
        )
    )
    assert c is None
    view = shared.view()
    fact = list(view.facts.values())[0]
    assert fact.value == NumericValue(amount=2.0)
    assert view.conflicts == []
    assert len(view.resolved_conflicts) == 1
    assert view.resolved_conflicts[0].reason == "higher source priority preferred (5 > 2)"


def test_publish_prefers_explicit_source_tier_when_provided() -> None:
    shared = SharedState()
    shared.publish(
        _fact(
            "k",
            1,
            "root.0",
            source_urls=("https://dart.fss.or.kr/dsaf001/main.do",),
            source_tier=1,
        )
    )
    c = shared.publish(
        _fact(
            "k",
            2,
            "root.1",
            source_urls=("https://example.com/custom-source",),
            source_tier=5,
        )
    )
    assert c is None
    view = shared.view()
    fact = list(view.facts.values())[0]
    assert fact.value == NumericValue(amount=2.0)
    assert len(view.resolved_conflicts) == 1
    assert view.resolved_conflicts[0].reason == "higher source priority preferred (5 > 1)"


def test_publish_keeps_conflict_when_source_tier_matches() -> None:
    shared = SharedState()
    shared.publish(
        _fact(
            "k",
            1,
            "root.0",
            source_urls=("https://www.reuters.com/markets/test",),
        )
    )
    c = shared.publish(
        _fact(
            "k",
            2,
            "root.1",
            source_urls=("https://www.bloomberg.com/news/test",),
        )
    )
    assert c is not None
    view = shared.view()
    fact = list(view.facts.values())[0]
    assert fact.value == NumericValue(amount=1.0)
    assert len(view.conflicts) == 1
    assert view.resolved_conflicts == []
