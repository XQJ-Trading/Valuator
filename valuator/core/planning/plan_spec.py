"""Root decomposition validation (boundary): Phase-2 tracks depend on Phase-1 slots."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..types import TaskSpec


class Phase1SlotSpec(BaseModel):
    """Documentation shape for collection slots; optional future wiring."""

    model_config = ConfigDict(extra="forbid")

    description: str = ""
    tool_hint: str = ""


class Phase2TrackSpec(BaseModel):
    """Analysis track that must depend on Phase-1 sibling indices."""

    model_config = ConfigDict(extra="forbid")

    description: str = ""
    depends_on_phase1_indices: list[int] = Field(default_factory=list)


class RootPlanSpec(BaseModel):
    """Optional explicit plan; root DECOMPOSE can stay free-form if validation passes below."""

    model_config = ConfigDict(extra="forbid")

    phase1_slots: list[Phase1SlotSpec] = Field(default_factory=list)
    phase2_tracks: list[Phase2TrackSpec] = Field(default_factory=list)


def validate_root_decomposition(children: tuple[TaskSpec, ...]) -> str | None:
    """Require depends_on_siblings to reference only phase-1 children (no depends_on_siblings)."""
    n = len(children)
    phase1_indices = frozenset(
        i for i, s in enumerate(children) if not s.depends_on_siblings
    )
    for i, spec in enumerate(children):
        for dep in spec.depends_on_siblings:
            if dep < 0 or dep >= n:
                return (
                    f"depends_on_siblings index {dep} out of range "
                    f"for child {i} (n={n})"
                )
            if dep not in phase1_indices:
                return (
                    f"child {i} depends_on_siblings references {dep} "
                    "which is not a phase-1 child (phase-1 = empty depends_on_siblings)"
                )
    return None
