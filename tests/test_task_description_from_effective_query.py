"""task_description_from_effective_query strips transport markers for display parity."""

from valuator.session.browse_tree import task_description_from_effective_query


def test_strips_thinking_level_and_query_block() -> None:
    raw = "[THINKING_LEVEL]\nhigh\n\n[QUERY]\nAnalyze AMZN"
    assert task_description_from_effective_query(raw) == "Analysis: Analyze AMZN"


def test_plain_query_unchanged_modulo_spacing() -> None:
    assert task_description_from_effective_query("Analyze AMZN") == "Analysis: Analyze AMZN"
