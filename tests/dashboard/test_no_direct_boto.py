"""Ensure dashboard and cogos routers don't import boto3 directly.

All AWS access should go through the CogtainerRuntime abstraction
(via create_executor_runtime) so that local/docker/AWS runtimes work
transparently.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Directories whose .py files must not import boto3
_CHECKED_DIRS = [
    Path("src/dashboard/routers"),
    Path("src/cogos/io"),
]

# Files that are explicitly allowed to use boto3 (legacy, should be migrated)
_ALLOWED_FILES: set[str] = set()


def _find_boto_imports(filepath: Path) -> list[int]:
    """Return line numbers where boto3 is imported."""
    source = filepath.read_text()
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "boto3" or alias.name.startswith("boto3."):
                    lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "boto3" or node.module.startswith("boto3.")):
                lines.append(node.lineno)
    return lines


def test_no_boto3_in_dashboard_routers_and_cogos_io():
    root = Path(__file__).resolve().parents[2]
    violations: list[str] = []
    for check_dir in _CHECKED_DIRS:
        full_dir = root / check_dir
        if not full_dir.exists():
            continue
        for py_file in sorted(full_dir.rglob("*.py")):
            rel = str(py_file.relative_to(root))
            if rel in _ALLOWED_FILES:
                continue
            lines = _find_boto_imports(py_file)
            for line in lines:
                violations.append(f"{rel}:{line}")
    assert not violations, (
        "Found direct boto3 imports — use CogtainerRuntime instead:\n  "
        + "\n  ".join(violations)
    )
