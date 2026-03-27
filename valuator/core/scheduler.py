from __future__ import annotations

from collections import deque

from valuator.tools.base import ToolResult

from .shared_state import SharedState
from .task import AtomicTask, ComplexTask, Task
from .types import Action, TaskDecision, TaskSpec, TaskState


class Scheduler:
    def __init__(self, max_steps_per_task: int = 20, concurrency: int = 4) -> None:
        self._tasks: dict[str, Task] = {}
        self._dependencies: dict[str, set[str]] = {}
        self._dependents: dict[str, set[str]] = {}
        self._waiting_facts: dict[str, set[str]] = {}
        self._ready_queue: deque[str] = deque()
        self._ready_ids: set[str] = set()
        self._max_steps = max_steps_per_task
        self._concurrency = concurrency

    @property
    def max_steps_per_task(self) -> int:
        return self._max_steps

    @property
    def concurrency(self) -> int:
        return self._concurrency

    def register(self, task: Task, *, depends_on: list[str] | None = None) -> None:
        self._tasks[task.id] = task
        unresolved = [
            dep_id
            for dep_id in depends_on or []
            if dep_id in self._tasks and self._tasks[dep_id].state != TaskState.DONE
        ]
        self._set_task_dependencies(task.id, unresolved)
        if task.state == TaskState.CREATED:
            if unresolved:
                task.state = TaskState.CREATED
            else:
                self._mark_ready(task)

    def get_task(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def ready_tasks(self, limit: int | None = None) -> list[Task]:
        if not self._ready_queue:
            for task in self._tasks.values():
                if task.state == TaskState.READY:
                    self._enqueue_ready(task.id)

        max_ready = self._concurrency if limit is None else min(limit, self._concurrency)
        ready: list[Task] = []
        while self._ready_queue and len(ready) < max_ready:
            task_id = self._ready_queue.popleft()
            self._ready_ids.discard(task_id)
            task = self._tasks.get(task_id)
            if task is None or task.state != TaskState.READY:
                continue
            ready.append(task)
        return ready

    def is_complete(self) -> bool:
        if not self._tasks:
            return False
        return all(
            task.state in (TaskState.DONE, TaskState.FAILED)
            for task in self._tasks.values()
        )

    def has_deadlock(self) -> bool:
        return (
            not self.is_complete()
            and not any(task.state == TaskState.READY for task in self._tasks.values())
            and not any(task.state == TaskState.RUNNING for task in self._tasks.values())
        )

    def apply_decision(
        self,
        task: Task,
        decision: TaskDecision,
        shared: SharedState,
    ) -> list[str]:
        self._discard_ready(task.id)
        task.step_count += 1
        newly_ready: list[str] = []

        match decision.action:
            case Action.DECOMPOSE:
                parent = self._promote(task)
                children = self._create_children(parent, decision.children)
                shared.remove_task_waits(parent.id)
                self._waiting_facts.pop(parent.id, None)
                self._clear_task_dependencies(parent.id)
                for child, depends_on in children:
                    self.register(child, depends_on=depends_on)
                    if child.state == TaskState.READY:
                        newly_ready.append(child.id)
                parent.state = TaskState.WAITING

            case Action.EXECUTE:
                shared.remove_task_waits(task.id)
                self._waiting_facts.pop(task.id, None)
                self._clear_task_dependencies(task.id)
                task.state = TaskState.RUNNING

            case Action.WAIT:
                shared.remove_task_waits(task.id)
                self._waiting_facts.pop(task.id, None)
                self._clear_task_dependencies(task.id)

                unresolved_facts = []
                for fact_key in decision.wait_for_facts:
                    if shared.has(fact_key):
                        continue
                    shared.subscribe(fact_key, task.id)
                    unresolved_facts.append(fact_key)

                unresolved_tasks = [
                    dep_id
                    for dep_id in decision.wait_for
                    if dep_id in self._tasks
                    and self._tasks[dep_id].state != TaskState.DONE
                ]
                self._set_task_dependencies(task.id, unresolved_tasks)
                if unresolved_facts:
                    self._waiting_facts[task.id] = set(unresolved_facts)

                if unresolved_facts or unresolved_tasks:
                    task.state = TaskState.WAITING
                else:
                    self._mark_ready(task, newly_ready)

            case Action.AGGREGATE:
                shared.remove_task_waits(task.id)
                self._waiting_facts.pop(task.id, None)
                self._clear_task_dependencies(task.id)
                task.state = TaskState.DONE
                task.output = decision.output
                for key, value in decision.facts.items():
                    shared.publish(key, value, task.id)
                    for waiter_id in shared.drain_waiters(key):
                        waits = self._waiting_facts.get(waiter_id)
                        if waits is not None:
                            waits.discard(key)
                            if not waits:
                                self._waiting_facts.pop(waiter_id, None)
                        self._maybe_ready(waiter_id, newly_ready)
                newly_ready.extend(self._release_dependents(task.id))
                newly_ready.extend(self._propagate_completion(task))

            case Action.FINALIZE:
                shared.remove_task_waits(task.id)
                self._waiting_facts.pop(task.id, None)
                self._clear_task_dependencies(task.id)
                task.state = TaskState.DONE
                task.output = decision.output
                newly_ready.extend(self._release_dependents(task.id))
                newly_ready.extend(self._propagate_completion(task))

            case Action.FAIL:
                self.mark_failed(task, decision.reason or "task failed")

        return list(dict.fromkeys(newly_ready))

    def mark_tool_complete(self, task: Task, result: ToolResult) -> None:
        task.tool_results.append(result)
        task.last_tool_success = result.success
        self._mark_ready(task)

    def mark_failed(self, task: Task, reason: str) -> None:
        if task.state == TaskState.FAILED:
            return
        self._discard_ready(task.id)
        task.state = TaskState.FAILED
        task.error = reason
        self._clear_task_dependencies(task.id)
        self._waiting_facts.pop(task.id, None)
        for child in task.children():
            self.mark_failed(child, f"ancestor {task.id} failed")
        for dependent_id in list(self._dependents.pop(task.id, set())):
            dependent = self._tasks.get(dependent_id)
            if dependent is not None:
                self.mark_failed(dependent, f"dependency {task.id} failed")
        self._check_parent_after_child_failure(task)

    def _create_children(
        self,
        parent: ComplexTask,
        specs: list[TaskSpec],
    ) -> list[tuple[Task, list[str]]]:
        created: list[tuple[Task, list[str]]] = []
        start_index = len(parent.children())
        children: list[Task] = []
        for offset, spec in enumerate(specs):
            child_id = f"{parent.id}.{start_index + offset}"
            child: Task
            if spec.tool_hint:
                child = AtomicTask(
                    id=child_id,
                    description=spec.description,
                    tool_hint=spec.tool_hint,
                    decide=parent.decider,
                )
            else:
                child = ComplexTask(
                    id=child_id,
                    description=spec.description,
                    tool_hint=spec.tool_hint,
                    decide=parent.decider,
                )
            parent.add_child(child)
            children.append(child)
        for index, spec in enumerate(specs):
            depends_on = [
                children[sibling_index].id
                for sibling_index in spec.depends_on_siblings
                if 0 <= sibling_index < len(children)
            ]
            created.append((children[index], depends_on))
        return created

    def validate_decomposition(
        self,
        task: Task,
        specs: list[TaskSpec],
    ) -> str | None:
        existing = {
            self._child_signature(child.description, child.tool_hint): child.id
            for child in task.children()
        }
        proposed: dict[str, str] = {}
        duplicates_existing: list[str] = []
        duplicates_proposed: list[str] = []

        for spec in specs:
            signature = self._child_signature(spec.description, spec.tool_hint)
            if signature in existing:
                duplicates_existing.append(spec.description)
                continue
            if signature in proposed:
                duplicates_proposed.append(spec.description)
                continue
            proposed[signature] = spec.description

        if not duplicates_existing and not duplicates_proposed:
            return None

        parts: list[str] = []
        if duplicates_existing:
            parts.append(
                "duplicates existing children: "
                + ", ".join(dict.fromkeys(duplicates_existing))
            )
        if duplicates_proposed:
            parts.append(
                "duplicates within proposed children: "
                + ", ".join(dict.fromkeys(duplicates_proposed))
            )
        return "decompose action would create duplicate children; " + "; ".join(parts)

    def _promote(self, task: Task) -> ComplexTask:
        if isinstance(task, ComplexTask):
            return task

        promoted = ComplexTask(
            id=task.id,
            description=task.description,
            tool_hint=task.tool_hint,
            decide=task.decider,
        )
        task.copy_runtime_to(promoted)
        self._tasks[task.id] = promoted

        parent = self._tasks.get(task.parent_id or "")
        if isinstance(parent, ComplexTask):
            parent.replace_child(task, promoted)
        return promoted

    def _propagate_completion(self, task: Task) -> list[str]:
        if task.parent_id is None:
            return []

        parent = self._tasks.get(task.parent_id)
        if parent is None:
            return []

        parent.child_outputs[task.id] = task.output
        if parent.state != TaskState.WAITING:
            return []

        child_states = [child.state for child in parent.children()]
        if not child_states:
            return []
        all_terminal = all(
            s in (TaskState.DONE, TaskState.FAILED) for s in child_states
        )
        has_success = any(s == TaskState.DONE for s in child_states)
        if all_terminal and has_success:
            self._mark_ready(parent)
            return [parent.id]
        return []

    def _check_parent_after_child_failure(self, task: Task) -> None:
        parent = self._tasks.get(task.parent_id or "")
        if parent is None or parent.state in (TaskState.DONE, TaskState.FAILED):
            return
        child_states = [child.state for child in parent.children()]
        all_terminal = all(
            s in (TaskState.DONE, TaskState.FAILED) for s in child_states
        )
        if not all_terminal:
            return
        if any(s == TaskState.DONE for s in child_states):
            self._mark_ready(parent)
        else:
            self.mark_failed(parent, f"all children failed (last: {task.id})")

    @staticmethod
    def _child_signature(description: str, tool_hint: str) -> str:
        normalized_description = " ".join(description.split()).casefold()
        normalized_tool_hint = tool_hint.strip().casefold()
        return f"{normalized_tool_hint}|{normalized_description}"

    def _set_task_dependencies(self, task_id: str, dependency_ids: list[str]) -> None:
        self._clear_task_dependencies(task_id)
        if not dependency_ids:
            self._dependencies[task_id] = set()
            return
        dependencies = set(dependency_ids)
        self._dependencies[task_id] = dependencies
        for dependency_id in dependencies:
            self._dependents.setdefault(dependency_id, set()).add(task_id)

    def _clear_task_dependencies(self, task_id: str) -> None:
        dependencies = self._dependencies.pop(task_id, set())
        for dependency_id in dependencies:
            dependents = self._dependents.get(dependency_id)
            if dependents is None:
                continue
            dependents.discard(task_id)
            if not dependents:
                self._dependents.pop(dependency_id, None)

    def _release_dependents(self, completed_task_id: str) -> list[str]:
        dependents = list(self._dependents.pop(completed_task_id, set()))
        newly_ready: list[str] = []
        for dependent_id in dependents:
            dependencies = self._dependencies.get(dependent_id)
            if dependencies is None:
                continue
            dependencies.discard(completed_task_id)
            if dependencies:
                continue
            self._maybe_ready(dependent_id, newly_ready)
        return newly_ready

    def _maybe_ready(self, task_id: str, newly_ready: list[str]) -> None:
        task = self._tasks.get(task_id)
        if task is None or task.state in (TaskState.DONE, TaskState.FAILED):
            return
        if self._dependencies.get(task_id):
            return
        if self._waiting_facts.get(task_id):
            return
        self._mark_ready(task, newly_ready)

    def requeue_ready(self, task: Task) -> None:
        if task.state != TaskState.READY:
            return
        self._discard_ready(task.id)
        self._enqueue_ready(task.id)

    def _mark_ready(self, task: Task, newly_ready: list[str] | None = None) -> None:
        if task.state in (TaskState.DONE, TaskState.FAILED):
            return
        task.state = TaskState.READY
        if self._enqueue_ready(task.id) and newly_ready is not None:
            newly_ready.append(task.id)

    def _enqueue_ready(self, task_id: str) -> bool:
        if task_id in self._ready_ids:
            return False
        self._ready_queue.append(task_id)
        self._ready_ids.add(task_id)
        return True

    def _discard_ready(self, task_id: str) -> None:
        self._ready_ids.discard(task_id)
