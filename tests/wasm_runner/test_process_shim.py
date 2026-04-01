"""Tests for ProcessShim — env, argv, exit."""

import pytest

from wasm_runner.shim.process import ProcessShim
from wasm_runner.types import IsolateConfig


class TestEnv:
    def test_env_returns_config_env(self):
        config = IsolateConfig(
            process_id="p1", run_id="r1",
            env={"HOME": "/home/agent", "USER": "agent"},
        )
        ps = ProcessShim(config)
        assert ps.env == {"HOME": "/home/agent", "USER": "agent"}

    def test_env_is_read_only(self):
        config = IsolateConfig(process_id="p1", run_id="r1", env={"K": "V"})
        ps = ProcessShim(config)
        with pytest.raises((TypeError, AttributeError)):
            ps.env["NEW"] = "val"  # type: ignore[index]


class TestArgv:
    def test_argv_returns_list(self):
        config = IsolateConfig(process_id="p1", run_id="r1")
        ps = ProcessShim(config)
        assert isinstance(ps.argv, list)


class TestExit:
    def test_exit_sets_code(self):
        config = IsolateConfig(process_id="p1", run_id="r1")
        ps = ProcessShim(config)
        assert ps.exited is False
        assert ps.exit_code is None
        ps.exit(42)
        assert ps.exited is True
        assert ps.exit_code == 42

    def test_exit_default_code_zero(self):
        config = IsolateConfig(process_id="p1", run_id="r1")
        ps = ProcessShim(config)
        ps.exit()
        assert ps.exit_code == 0

    def test_double_exit_is_noop(self):
        config = IsolateConfig(process_id="p1", run_id="r1")
        ps = ProcessShim(config)
        ps.exit(1)
        ps.exit(2)  # second exit should not change the code
        assert ps.exit_code == 1
