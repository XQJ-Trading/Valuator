from __future__ import annotations

from valuator.core.planning.plan_spec import validate_root_decomposition
from valuator.core.scheduler import Scheduler
from valuator.core.shared_state import SharedState
from valuator.core.task import AtomicTask, ComplexTask
from valuator.core.types import Action, TaskDecision, TaskSpec, TaskState, TaskWorkPhase


def test_allowed_actions_keep_decompose_in_schema_while_runtime_rejects() -> None:
    """DECOMPOSE remains in allowed_actions during SYNTHESIZE so JSON schema can list it; Agent rejects."""
    parent = ComplexTask(id="root", description="x")
    parent.work_phase = TaskWorkPhase.SYNTHESIZE
    from valuator.core.planning.actions import allowed_actions_for_task

    allowed = allowed_actions_for_task(parent, allow_decompose=True)
    assert Action.DECOMPOSE in allowed


def test_validate_root_decomposition_phase2_must_depend_on_phase1() -> None:
    ok = (
        TaskSpec(description="a", depends_on_siblings=[]),
        TaskSpec(description="b", depends_on_siblings=[]),
        TaskSpec(description="c", depends_on_siblings=[0, 1]),
    )
    assert validate_root_decomposition(ok) is None

    bad = (
        TaskSpec(description="a", depends_on_siblings=[]),
        TaskSpec(description="b", depends_on_siblings=[1]),
        TaskSpec(description="c", depends_on_siblings=[0]),
    )
    err = validate_root_decomposition(bad)
    assert err is not None
    assert "phase-1" in err


def test_scheduler_sets_synthesize_when_child_finishes() -> None:
    scheduler = Scheduler()
    shared = SharedState()
    root = AtomicTask(id="root", description="root task", task_name="root_task")
    scheduler.register(root)
    scheduler.apply_decision(
        root,
        TaskDecision(
            action=Action.DECOMPOSE,
            children=[
                TaskSpec(
                    description="child task",
                    task_name="child_task",
                    tool_hint="dummy_tool",
                )
            ],
        ),
        shared,
    )
    parent = scheduler.get_task("root")
    assert isinstance(parent, ComplexTask)
    assert parent.work_phase is TaskWorkPhase.COLLECT
    child = scheduler.get_task("root.0")
    assert child is not None
    scheduler.apply_decision(
        child,
        TaskDecision(action=Action.AGGREGATE, output="done", facts={}),
        shared,
    )
    assert parent.state is TaskState.READY
    assert parent.work_phase is TaskWorkPhase.SYNTHESIZE
