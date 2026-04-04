from __future__ import annotations

from ..task import Task
from ..types import Action


def allowed_actions_for_task(
    task: Task, *, allow_decompose: bool = True
) -> list[Action]:
    actions = list(Action)
    if not allow_decompose:
        actions = [action for action in actions if action is not Action.DECOMPOSE]
    if task.last_tool_success is True:
        actions = [action for action in actions if action is not Action.EXECUTE]
    if task.parent_id is not None:
        actions = [action for action in actions if action is not Action.FINALIZE]
    return actions
