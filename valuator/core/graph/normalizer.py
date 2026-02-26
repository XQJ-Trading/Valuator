"""Plan graph normalization utilities."""

from __future__ import annotations

from ..contracts.plan import Plan


def ensure_recursive_graph(
    plan: Plan,
) -> Plan:
    """Backward-compatible no-op normalizer.

    Plan correction logic was removed to keep the contract strict.
    Validation should fail on malformed plans instead of auto-rewriting them.
    """
    if not plan.tasks:
        raise ValueError("plan must include at least one task")
    return plan
