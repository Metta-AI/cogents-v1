"""run-task: Loads a task, sets it to running, and dispatches to the appropriate executor.

Triggered by task:dispatch event.
"""

from __future__ import annotations

from uuid import UUID

from brain.db.models import Event, TaskStatus
from brain.db.repository import Repository


def run(repo: Repository, event: dict, config: dict) -> list[Event]:
    """Load task from dispatch event, set running, emit executor payload."""
    payload = event.get("payload", {})
    task_id_str = payload.get("task_id")
    if not task_id_str:
        return [_error_event("run-task: missing task_id in payload")]

    task = repo.get_task(UUID(task_id_str))
    if not task:
        return [_error_event(f"run-task: task {task_id_str} not found")]

    if task.status != TaskStatus.RUNNABLE:
        return []  # Already picked up or completed

    # Set task to running
    repo.update_task_status(task.id, TaskStatus.RUNNING)

    # Load the program to get defaults
    program = repo.get_program(task.program_name)
    if not program:
        repo.update_task_status(task.id, TaskStatus.RUNNABLE)
        return [_error_event(f"run-task: program '{task.program_name}' not found")]

    # Resolve runner: task override > program default > lambda
    runner = task.runner or program.runner or "lambda"

    # Merge tools and memory keys
    merged_tools = list(set((program.tools or []) + (task.tools or [])))
    merged_memory_keys = list(set((program.memory_keys or []) + (task.memory_keys or [])))

    # Build the execution event — this gets picked up by the orchestrator
    # which dispatches to Lambda or ECS based on runner
    return [
        Event(
            event_type=f"task:execute:{runner}",
            source="run-task",
            payload={
                "task_id": str(task.id),
                "task_name": task.name,
                "program_name": task.program_name,
                "runner": runner,
                "clear_context": task.clear_context,
                "task": {
                    "id": str(task.id),
                    "content": task.content,
                    "memory_keys": merged_memory_keys,
                    "tools": merged_tools,
                    "clear_context": task.clear_context,
                },
            },
        )
    ]


def _error_event(message: str) -> Event:
    return Event(
        event_type="task:error",
        source="run-task",
        payload={"error": message},
    )
