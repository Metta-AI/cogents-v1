"""Process shim — env, argv, exit for the Wasm isolate."""

from __future__ import annotations

from types import MappingProxyType

from wasm_runner.types import IsolateConfig


class ProcessShim:
    """POSIX process interface for the isolate.

    Provides read-only env/argv and exit signaling.
    """

    def __init__(self, config: IsolateConfig) -> None:
        self._config = config
        self._env = MappingProxyType(dict(config.env))  # frozen copy
        self._exited = False
        self._exit_code: int | None = None

    @property
    def env(self) -> MappingProxyType:
        return self._env

    @property
    def argv(self) -> list[str]:
        return [self._config.process_id]

    def exit(self, code: int = 0) -> None:
        if self._exited:
            return  # second exit is no-op
        self._exited = True
        self._exit_code = code

    @property
    def exited(self) -> bool:
        return self._exited

    @property
    def exit_code(self) -> int | None:
        return self._exit_code
