"""Virtual filesystem — POSIX fs operations backed by CogOS capabilities."""

from __future__ import annotations

import time

from wasm_runner.bridge.audit import AuditLogger
from wasm_runner.bridge.capability_bridge import CapabilityBridge
from wasm_runner.shim.path_translator import translate_path
from wasm_runner.types import EPHEMERAL, IsolateConfig, StatResult, SyscallEvent


class VirtualFS:
    """POSIX-like filesystem backed by CogOS files capability.

    Persistent paths (/home/agent/workspace/*) go through the bridge.
    Ephemeral paths (/tmp/*) are stored in an in-memory dict.
    All other paths raise PermissionError (EPERM).
    """

    def __init__(self, bridge: CapabilityBridge, audit: AuditLogger, config: IsolateConfig) -> None:
        self._bridge = bridge
        self._audit = audit
        self._config = config
        self._tmp: dict[str, bytes] = {}  # ephemeral /tmp store

    def _emit(self, op: str, args: dict, result: str = "ok") -> None:
        self._audit.log(SyscallEvent(
            op=op, args=args, process_id=self._config.process_id,
            timestamp_ms=int(time.time() * 1000), result=result,
        ))

    def _translate(self, path: str) -> str:
        """Translate path, emitting EPERM audit event on failure."""
        return translate_path(path, file_prefix=self._config.file_prefix)

    async def read_file(self, path: str) -> bytes:
        try:
            key = self._translate(path)
        except PermissionError:
            self._emit("fs.readFile", {"path": path}, "EPERM")
            raise

        if key == EPHEMERAL:
            # Extract the /tmp-relative key
            tmp_key = path  # use full path as tmp key for uniqueness
            self._emit("fs.readFile", {"path": path})
            if tmp_key not in self._tmp:
                raise FileNotFoundError(f"File not found: {path}")
            return self._tmp[tmp_key]

        self._emit("fs.readFile", {"path": path, "key": key})
        return await self._bridge.files_read(key)

    async def write_file(self, path: str, data: bytes) -> None:
        try:
            key = self._translate(path)
        except PermissionError:
            self._emit("fs.writeFile", {"path": path}, "EPERM")
            raise

        if key == EPHEMERAL:
            self._tmp[path] = data
            return  # no bridge call, no audit for ephemeral

        self._emit("fs.writeFile", {"path": path, "key": key})
        await self._bridge.files_write(key, data)

    async def readdir(self, path: str) -> list[str]:
        try:
            key = self._translate(path)
        except PermissionError:
            self._emit("fs.readdir", {"path": path}, "EPERM")
            raise

        if key == EPHEMERAL:
            self._emit("fs.readdir", {"path": path})
            # List files in /tmp that are direct children of path
            prefix = path if path.endswith("/") else path + "/"
            results = []
            for k in self._tmp:
                if k.startswith(prefix):
                    relative = k[len(prefix):]
                    # Only direct children (no nested /)
                    if "/" not in relative:
                        results.append(relative)
            return sorted(results)

        self._emit("fs.readdir", {"path": path, "key": key})
        prefix = key if key.endswith("/") else key + "/"
        keys = await self._bridge.files_search(prefix)
        # Return just the filename part
        return [k[len(prefix):] for k in keys if k.startswith(prefix) and "/" not in k[len(prefix):]]

    async def stat(self, path: str) -> StatResult:
        try:
            key = self._translate(path)
        except PermissionError:
            self._emit("fs.stat", {"path": path}, "EPERM")
            raise

        if key == EPHEMERAL:
            self._emit("fs.stat", {"path": path})
            if path not in self._tmp:
                raise FileNotFoundError(f"File not found: {path}")
            data = self._tmp[path]
            return StatResult(size=len(data), is_file=True, is_directory=False)

        self._emit("fs.stat", {"path": path, "key": key})
        data = await self._bridge.files_read(key)
        return StatResult(size=len(data), is_file=True, is_directory=False)

    async def unlink(self, path: str) -> None:
        try:
            key = self._translate(path)
        except PermissionError:
            self._emit("fs.unlink", {"path": path}, "EPERM")
            raise

        if key == EPHEMERAL:
            self._emit("fs.unlink", {"path": path})
            if path in self._tmp:
                del self._tmp[path]
            return

        self._emit("fs.unlink", {"path": path, "key": key})
        await self._bridge.files_delete(key)

    async def mkdir(self, path: str) -> None:
        # No-op for key-based stores — directories are implicit
        try:
            self._translate(path)
        except PermissionError:
            self._emit("fs.mkdir", {"path": path}, "EPERM")
            raise
