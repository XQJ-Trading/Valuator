from __future__ import annotations

from valuator.core import Action, AtomicTask, ComplexTask, Scheduler, SharedState
from valuator.core.types import TaskDecision, TaskSpec, TaskState


def test_scheduler_promotes_atomic_task_on_decompose() -> None:
    scheduler = Scheduler()
    shared = SharedState()
    root = AtomicTask(id="root", description="root task")

    scheduler.register(root)
    newly_ready = scheduler.apply_decision(
        root,
        TaskDecision(
            action=Action.DECOMPOSE,
            children=[TaskSpec(description="child task", tool_hint="dummy_tool")],
            reason="split",
        ),
        shared,
    )

    promoted = scheduler.get_task("root")
    child = scheduler.get_task("root.0")

    assert isinstance(promoted, ComplexTask)
    assert promoted is not None and promoted.state is TaskState.WAITING
    assert isinstance(child, AtomicTask)
    assert newly_ready == ["root.0"]


def test_scheduler_wakes_waiting_task_when_fact_is_published() -> None:
    scheduler = Scheduler()
    shared = SharedState()
    producer = ComplexTask(id="producer", description="producer")
    consumer = ComplexTask(id="consumer", description="consumer")

    scheduler.register(producer)
    scheduler.register(consumer)

    waiting_ready = scheduler.apply_decision(
        consumer,
        TaskDecision(
            action=Action.WAIT,
            wait_for_facts=["wacc"],
            reason="need wacc",
        ),
        shared,
    )
    assert waiting_ready == []
    assert consumer.state is TaskState.WAITING

    newly_ready = scheduler.apply_decision(
        producer,
        TaskDecision(
            action=Action.AGGREGATE,
            output="WACC 9.5%",
            facts={"wacc": 0.095},
            reason="publish fact",
        ),
        shared,
    )

    assert shared.get("wacc") == 0.095
    assert consumer.state is TaskState.READY
    assert newly_ready == ["consumer"]


def test_scheduler_wait_for_task_dependency_releases_on_completion() -> None:
    scheduler = Scheduler()
    shared = SharedState()
    dependency = ComplexTask(id="dependency", description="dependency")
    waiter = ComplexTask(id="waiter", description="waiter")

    scheduler.register(dependency)
    scheduler.register(waiter)
    scheduler.apply_decision(
        waiter,
        TaskDecision(
            action=Action.WAIT,
            wait_for=["dependency"],
            reason="wait for dependency",
        ),
        shared,
    )

    assert waiter.state is TaskState.WAITING

    newly_ready = scheduler.apply_decision(
        dependency,
        TaskDecision(
            action=Action.AGGREGATE,
            output="done",
            reason="complete dependency",
        ),
        shared,
    )

    assert waiter.state is TaskState.READY
    assert newly_ready == ["waiter"]


def test_scheduler_requeues_ready_tasks_in_fifo_order() -> None:
    scheduler = Scheduler(concurrency=1)
    first = ComplexTask(id="first", description="first")
    second = ComplexTask(id="second", description="second")
    third = ComplexTask(id="third", description="third")

    scheduler.register(first)
    scheduler.register(second)
    scheduler.register(third)

    ready = scheduler.ready_tasks()

    assert [task.id for task in ready] == ["first"]

    scheduler.requeue_ready(first)

    next_ready = scheduler.ready_tasks()
    final_ready = scheduler.ready_tasks()

    assert [task.id for task in next_ready] == ["second"]
    assert [task.id for task in final_ready] == ["third"]


def test_scheduler_does_not_wake_parent_when_sibling_is_still_waiting() -> None:
    scheduler = Scheduler()
    shared = SharedState()
    parent = ComplexTask(id="root", description="root")

    scheduler.register(parent)
    scheduler.apply_decision(
        parent,
        TaskDecision(
            action=Action.DECOMPOSE,
            children=[
                TaskSpec(description="done child"),
                TaskSpec(description="waiting child"),
            ],
            reason="split work",
        ),
        shared,
    )

    done_child = scheduler.get_task("root.0")
    waiting_child = scheduler.get_task("root.1")

    assert done_child is not None
    assert waiting_child is not None

    scheduler.apply_decision(
        waiting_child,
        TaskDecision(
            action=Action.WAIT,
            wait_for_facts=["alpha"],
            reason="need alpha",
        ),
        shared,
    )
    newly_ready = scheduler.apply_decision(
        done_child,
        TaskDecision(
            action=Action.AGGREGATE,
            output="done",
            reason="complete child",
        ),
        shared,
    )

    assert parent.state is TaskState.WAITING
    assert "root" not in newly_ready


def test_scheduler_rejects_duplicate_decomposition_against_existing_children() -> None:
    scheduler = Scheduler()
    parent = ComplexTask(id="root", description="root")
    parent.add_child(
        AtomicTask(id="root.0", description="Collect alpha", tool_hint="dummy_tool")
    )

    error = scheduler.validate_decomposition(
        parent,
        [TaskSpec(description="  collect   alpha  ", tool_hint="dummy_tool")],
    )

    assert error is not None
    assert "duplicate children" in error
