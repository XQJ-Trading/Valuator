from __future__ import annotations

from domain.query import QueryAnalysis, QueryUnit
from valuator.core.context import TaskContext
from valuator.core import Action, AtomicTask, ComplexTask, Scheduler
from valuator.core.types import TaskDecision, TaskSpec, TaskState


def test_scheduler_promotes_atomic_task_on_decompose() -> None:
    scheduler = Scheduler()
    root = AtomicTask(id="root", description="root task", task_name="root_task")

    scheduler.register(root)
    newly_ready = scheduler.apply_decision(
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
    )

    promoted = scheduler.get_task("root")
    child = scheduler.get_task("root.0")

    assert isinstance(promoted, ComplexTask)
    assert promoted is not None and promoted.state is TaskState.WAITING
    assert promoted.task_name == "root_task"
    assert isinstance(child, AtomicTask)
    assert child is not None and child.task_name == "child_task"
    assert newly_ready == ["root.0"]


def test_scheduler_wakes_waiting_task_when_dependency_task_completes() -> None:
    scheduler = Scheduler()
    producer = ComplexTask(id="producer", description="producer")
    consumer = ComplexTask(id="consumer", description="consumer")

    scheduler.register(producer)
    scheduler.register(consumer)

    waiting_ready = scheduler.apply_decision(
        consumer,
        TaskDecision(
            action=Action.WAIT,
            wait_for=["producer"],
        ),
    )
    assert waiting_ready == []
    assert consumer.state is TaskState.WAITING

    newly_ready = scheduler.apply_decision(
        producer,
        TaskDecision(
            action=Action.AGGREGATE,
            output="WACC 9.5%",
            facts={"wacc": 0.095},
        ),
    )

    # fact layer removed — published_facts stored on task
    assert producer.published_facts == {"wacc": 0.095}
    assert consumer.state is TaskState.READY
    assert newly_ready == ["consumer"]


def test_scheduler_wait_for_task_dependency_releases_on_completion() -> None:
    scheduler = Scheduler()
    dependency = ComplexTask(id="dependency", description="dependency")
    waiter = ComplexTask(id="waiter", description="waiter")

    scheduler.register(dependency)
    scheduler.register(waiter)
    scheduler.apply_decision(
        waiter,
        TaskDecision(
            action=Action.WAIT,
            wait_for=["dependency"],
        ),
    )

    assert waiter.state is TaskState.WAITING

    newly_ready = scheduler.apply_decision(
        dependency,
        TaskDecision(
            action=Action.AGGREGATE,
            output="done",
        ),
    )

    assert waiter.state is TaskState.READY
    assert newly_ready == ["waiter"]


def test_scheduler_wait_for_task_dependency_releases_on_failure() -> None:
    scheduler = Scheduler()
    dependency = ComplexTask(id="dependency", description="dependency")
    waiter = ComplexTask(id="waiter", description="waiter")

    scheduler.register(dependency)
    scheduler.register(waiter)
    scheduler.apply_decision(
        waiter,
        TaskDecision(
            action=Action.WAIT,
            wait_for=["dependency"],
        ),
    )

    assert waiter.state is TaskState.WAITING

    scheduler.mark_failed(dependency, "upstream unavailable")

    assert dependency.state is TaskState.FAILED
    assert waiter.state is TaskState.READY


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
    parent = ComplexTask(id="root", description="root")

    scheduler.register(parent)
    scheduler.apply_decision(
        parent,
        TaskDecision(
            action=Action.DECOMPOSE,
            children=[
                TaskSpec(description="done child", task_name="done_child"),
                TaskSpec(description="waiting child", task_name="waiting_child"),
            ],
        ),
    )

    done_child = scheduler.get_task("root.0")
    waiting_child = scheduler.get_task("root.1")

    assert done_child is not None
    assert waiting_child is not None

    scheduler.apply_decision(
        waiting_child,
        TaskDecision(
            action=Action.WAIT,
            wait_for=["root.0"],
        ),
    )
    newly_ready = scheduler.apply_decision(
        done_child,
        TaskDecision(
            action=Action.AGGREGATE,
            output="done",
        ),
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


def test_scheduler_child_signature_includes_execution_tool() -> None:
    scheduler = Scheduler()
    parent = ComplexTask(id="root", description="root")
    parent.add_child(
        AtomicTask(
            id="root.0",
            description="Collect alpha",
            execution_tool="dummy_tool",
        )
    )

    error = scheduler.validate_decomposition(
        parent,
        [
            TaskSpec(
                description="Collect alpha",
                execution_tool="opendart_financial_tool",
            )
        ],
    )

    assert error is None


def test_scheduler_copies_execution_tool_to_child_task() -> None:
    scheduler = Scheduler()
    root = ComplexTask(id="root", description="root")
    scheduler.register(root)

    scheduler.apply_decision(
        root,
        TaskDecision(
            action=Action.DECOMPOSE,
            children=[
                TaskSpec(
                    description="collect financials",
                    execution_tool="opendart_financial_tool",
                )
            ],
        ),
    )

    child = scheduler.get_task("root.0")
    assert isinstance(child, AtomicTask)
    assert child.execution_tool == "opendart_financial_tool"


def test_validate_wait_detects_direct_cycle() -> None:
    scheduler = Scheduler()
    task_a = ComplexTask(id="a", description="a")
    task_b = ComplexTask(id="b", description="b")

    scheduler.register(task_a)
    scheduler.register(task_b)
    scheduler.apply_decision(
        task_a,
        TaskDecision(
            action=Action.WAIT,
            wait_for=["b"],
        ),
    )

    error = scheduler.validate_wait("b", ["a"])

    assert error is not None
    assert "circular dependency" in error


def test_validate_wait_detects_transitive_cycle() -> None:
    scheduler = Scheduler()
    task_a = ComplexTask(id="a", description="a")
    task_b = ComplexTask(id="b", description="b")
    task_c = ComplexTask(id="c", description="c")

    scheduler.register(task_a)
    scheduler.register(task_b)
    scheduler.register(task_c)
    scheduler.apply_decision(
        task_a,
        TaskDecision(
            action=Action.WAIT,
            wait_for=["b"],
        ),
    )
    scheduler.apply_decision(
        task_b,
        TaskDecision(
            action=Action.WAIT,
            wait_for=["c"],
        ),
    )

    error = scheduler.validate_wait("c", ["a"])

    assert error is not None
    assert "circular dependency" in error


def test_validate_wait_allows_non_cyclic() -> None:
    scheduler = Scheduler()
    task_a = ComplexTask(id="a", description="a")
    task_b = ComplexTask(id="b", description="b")

    scheduler.register(task_a)
    scheduler.register(task_b)

    error = scheduler.validate_wait("a", ["b"])

    assert error is None


def test_validate_wait_skips_done_tasks() -> None:
    scheduler = Scheduler()
    task_a = ComplexTask(id="a", description="a")
    task_b = ComplexTask(id="b", description="b")

    scheduler.register(task_a)
    scheduler.register(task_b)
    scheduler.apply_decision(
        task_b,
        TaskDecision(
            action=Action.AGGREGATE,
            output="done",
        ),
    )

    error = scheduler.validate_wait("a", ["b"])

    assert error is None


def test_validate_wait_rejects_failed_only_dependencies() -> None:
    scheduler = Scheduler()
    task_a = ComplexTask(id="a", description="a")
    task_b = ComplexTask(id="b", description="b")

    scheduler.register(task_a)
    scheduler.register(task_b)
    scheduler.mark_failed(task_b, "upstream unavailable")

    error = scheduler.validate_wait("a", ["b"])

    assert error == "wait has no live dependencies; failed tasks: [b]"


def test_scheduler_wait_ignores_failed_dependencies_when_other_waits_remain() -> None:
    scheduler = Scheduler()
    task_a = ComplexTask(id="a", description="a")
    task_b = ComplexTask(id="b", description="b")
    task_c = ComplexTask(id="c", description="c")

    scheduler.register(task_a)
    scheduler.register(task_b)
    scheduler.register(task_c)
    scheduler.mark_failed(task_b, "upstream unavailable")

    scheduler.apply_decision(
        task_a,
        TaskDecision(
            action=Action.WAIT,
            wait_for=["b", "c"],
        ),
    )

    assert task_a.state is TaskState.WAITING
    assert scheduler.validate_wait("a", ["b", "c"]) is None

    scheduler.apply_decision(
        task_c,
        TaskDecision(
            action=Action.AGGREGATE,
            output="done",
        ),
    )

    assert task_a.state is TaskState.READY


def test_scheduler_fail_uses_decision_error() -> None:
    scheduler = Scheduler()
    root = ComplexTask(id="root", description="root")

    scheduler.register(root)
    newly_ready = scheduler.apply_decision(
        root,
        TaskDecision(
            action=Action.FAIL,
            output="upstream unavailable",
        ),
    )

    assert newly_ready == []
    assert root.state is TaskState.FAILED
    assert root.error == "upstream unavailable"


def test_scheduler_turns_facts_only_aggregate_into_structured_output() -> None:
    scheduler = Scheduler()
    root = ComplexTask(id="root", description="root")

    scheduler.register(root)
    scheduler.apply_decision(
        root,
        TaskDecision(
            action=Action.DECOMPOSE,
            children=[TaskSpec(description="collect facts")],
        ),
    )

    child = scheduler.get_task("root.0")
    assert child is not None

    scheduler.apply_decision(
        child,
        TaskDecision(
            action=Action.AGGREGATE,
            facts={"price_uplift": "could not verify"},
        ),
    )

    assert child.output is None
    assert child.completion_payload() == {
        "status": "facts_only",
        "facts": {"price_uplift": "could not verify"},
        "source_task_id": "root.0",
    }
    assert root.child_outputs["root.0"] == child.completion_payload()


def test_scheduler_stores_aggregate_facts_on_task() -> None:
    """After fact layer removal, facts are stored on task.published_facts only."""
    scheduler = Scheduler()
    root = ComplexTask(id="root", description="root", query_unit_ids=[0])

    scheduler.register(root)
    scheduler.apply_decision(
        root,
        TaskDecision(
            action=Action.AGGREGATE,
            facts={"iran_enrichment_level": {"value": 60, "grounded": True}},
        ),
    )

    assert root.published_facts == {
        "iran_enrichment_level": {"value": 60, "grounded": True},
    }


def test_scheduler_inherits_single_parent_query_unit_id() -> None:
    scheduler = Scheduler()
    root = ComplexTask(id="root", description="root", query_unit_ids=[2])

    scheduler.register(root)
    scheduler.apply_decision(
        root,
        TaskDecision(
            action=Action.DECOMPOSE,
            children=[TaskSpec(description="child task", task_name="child_task")],
        ),
    )

    child = scheduler.get_task("root.0")
    assert child is not None
    assert child.query_unit_ids == [2]


def test_scheduler_requires_child_query_unit_ids_for_multi_unit_parent() -> None:
    scheduler = Scheduler()
    parent = ComplexTask(id="root", description="root", query_unit_ids=[0, 1])

    error = scheduler.validate_decomposition(
        parent,
        [TaskSpec(description="child task", task_name="child_task")],
    )

    assert error == "decompose action requires child query_unit_ids"


def test_scheduler_wakes_wait_task_when_sibling_dependency_fails() -> None:
    scheduler = Scheduler()
    root = ComplexTask(id="root", description="root")

    scheduler.register(root)
    scheduler.apply_decision(
        root,
        TaskDecision(
            action=Action.DECOMPOSE,
            children=[
                TaskSpec(description="produce fact", task_name="producer"),
                TaskSpec(description="consume fact", task_name="consumer"),
            ],
        ),
    )

    producer = scheduler.get_task("root.0")
    consumer = scheduler.get_task("root.1")
    assert producer is not None and consumer is not None

    scheduler.apply_decision(
        consumer,
        TaskDecision(action=Action.WAIT, wait_for=["root.0"]),
    )
    assert consumer.state == TaskState.WAITING

    scheduler.mark_failed(producer, "too many invalid decisions")
    assert producer.state == TaskState.FAILED

    assert consumer.state == TaskState.READY
