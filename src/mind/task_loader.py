"""Load task definitions from a directory of Markdown, YAML, and Python files."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import yaml

from brain.db.models import Task, TaskStatus


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split optional YAML frontmatter from markdown body.

    Returns (frontmatter_dict, body). If no frontmatter, dict is empty.
    """
    if not text.startswith("---"):
        return {}, text

    # Find closing ---
    end = text.find("---", 3)
    if end == -1:
        return {}, text

    front = text[3:end].strip()
    body = text[end + 3 :].strip()
    fm = yaml.safe_load(front) if front else {}
    return fm if isinstance(fm, dict) else {}, body


def _task_from_dict(d: dict[str, Any]) -> Task:
    """Build a Task from a raw dict (YAML or frontmatter fields)."""
    status = TaskStatus.RUNNABLE
    if d.pop("disabled", False):
        status = TaskStatus.DISABLED

    # Normalise comma-separated strings into lists
    for list_field in ("memory_keys", "tools", "resources"):
        val = d.get(list_field)
        if isinstance(val, str):
            d[list_field] = [s.strip() for s in val.split(",") if s.strip()]

    d.setdefault("status", status)
    if isinstance(d.get("status"), str):
        d["status"] = TaskStatus(d["status"])

    return Task(**d)


def _load_markdown(path: Path, rel: str) -> list[Task]:
    """Load a single markdown file as a task."""
    text = path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)

    # Name from relative path without .md extension
    name = rel.removesuffix(".md")
    fm.setdefault("name", name)
    fm.setdefault("program_name", "do-content")
    fm["content"] = body

    return [_task_from_dict(fm)]


def _load_yaml(path: Path) -> list[Task]:
    """Load tasks from a YAML file."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return []

    # Top-level list
    if isinstance(raw, list):
        return [_task_from_dict(d) for d in raw]

    # Dict with 'tasks' key
    if isinstance(raw, dict) and "tasks" in raw:
        return [_task_from_dict(d) for d in raw["tasks"]]

    # Single task dict (must have 'name')
    if isinstance(raw, dict) and "name" in raw:
        return [_task_from_dict(raw)]

    return []


def _load_python(path: Path) -> list[Task]:
    """Load tasks from a Python file defining task or tasks at module level."""
    spec = importlib.util.spec_from_file_location("_task_module", path)
    if spec is None or spec.loader is None:
        return []

    module = importlib.util.module_from_spec(spec)
    # Temporarily add to sys.modules so relative imports work
    sys.modules["_task_module"] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    finally:
        sys.modules.pop("_task_module", None)

    tasks: list[Task] = []
    if hasattr(module, "tasks"):
        tasks.extend(module.tasks)
    elif hasattr(module, "task"):
        tasks.append(module.task)
    return tasks


def load_tasks_from_dir(tasks_dir: Path) -> list[Task]:
    """Recursively load task definitions from a directory.

    Supports .md, .yaml, .yml, and .py files. Files are processed in
    sorted order for deterministic results.
    """
    tasks: list[Task] = []

    for path in sorted(tasks_dir.rglob("*")):
        if not path.is_file():
            continue

        rel = str(path.relative_to(tasks_dir))
        suffix = path.suffix.lower()

        if suffix == ".md":
            tasks.extend(_load_markdown(path, rel))
        elif suffix in (".yaml", ".yml"):
            tasks.extend(_load_yaml(path))
        elif suffix == ".py":
            tasks.extend(_load_python(path))

    return tasks
