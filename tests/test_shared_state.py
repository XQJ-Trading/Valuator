"""SharedState tests — fact layer removed; stub SharedState is a no-op."""

from __future__ import annotations

from valuator.core.shared_state import SharedState


def test_shared_state_is_noop() -> None:
    shared = SharedState()
    assert shared.publish() is None
    assert shared.view().facts == {}
    assert shared.view_for().facts == {}
    assert shared.conflict_count() == 0
