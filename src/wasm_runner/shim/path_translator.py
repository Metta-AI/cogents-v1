"""Path translation: virtual POSIX paths to CogOS file keys."""

from __future__ import annotations

import posixpath

from wasm_runner.types import EPHEMERAL

# Virtual mount points
_WORKSPACE_ROOT = "/home/agent/workspace"
_TMP_ROOT = "/tmp"


def translate_path(virtual_path: str, file_prefix: str = "workspace/") -> str:
    """Translate a virtual POSIX path to a CogOS file key.

    Returns:
        A CogOS file key (e.g. "workspace/foo.txt") for persistent paths,
        or EPHEMERAL sentinel for /tmp paths.

    Raises:
        PermissionError: If the path is outside allowed mount points,
            contains traversal attacks, or is otherwise invalid.
    """
    if not virtual_path:
        raise PermissionError("EPERM: empty path")

    if "\x00" in virtual_path:
        raise PermissionError("EPERM: null byte in path")

    if not virtual_path.startswith("/"):
        raise PermissionError(f"EPERM: relative path not allowed: {virtual_path!r}")

    # Normalize: resolve . and .. but keep leading /
    had_trailing_slash = virtual_path.endswith("/")
    normalized = posixpath.normpath(virtual_path)

    # After normalization, check /tmp first
    if normalized == _TMP_ROOT or normalized.startswith(_TMP_ROOT + "/"):
        return EPHEMERAL

    # Check workspace
    if normalized == _WORKSPACE_ROOT:
        key = file_prefix.rstrip("/")
        return key + "/" if had_trailing_slash else key

    if normalized.startswith(_WORKSPACE_ROOT + "/"):
        relative = normalized[len(_WORKSPACE_ROOT) + 1:]  # strip prefix + /
        return file_prefix + relative

    raise PermissionError(f"EPERM: path outside allowed mounts: {virtual_path!r}")
