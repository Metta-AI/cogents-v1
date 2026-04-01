"""Tests for virtual POSIX path → CogOS file key translation."""

import pytest

from wasm_runner.shim.path_translator import translate_path
from wasm_runner.types import EPHEMERAL


class TestHappyPaths:
    def test_workspace_file(self):
        assert translate_path("/home/agent/workspace/foo.txt") == "workspace/foo.txt"

    def test_workspace_nested(self):
        assert translate_path("/home/agent/workspace/sub/dir/bar.py") == "workspace/sub/dir/bar.py"

    def test_workspace_root_trailing_slash(self):
        assert translate_path("/home/agent/workspace/") == "workspace/"

    def test_workspace_root_no_trailing_slash(self):
        assert translate_path("/home/agent/workspace") == "workspace"

    def test_custom_prefix(self):
        assert translate_path("/home/agent/workspace/x.txt", file_prefix="data/") == "data/x.txt"


class TestEphemeralTmp:
    def test_tmp_file(self):
        assert translate_path("/tmp/scratch.txt") == EPHEMERAL

    def test_tmp_nested(self):
        assert translate_path("/tmp/a/b/c.txt") == EPHEMERAL

    def test_tmp_root(self):
        assert translate_path("/tmp") == EPHEMERAL


class TestTraversalAttacks:
    def test_absolute_traversal(self):
        with pytest.raises(PermissionError):
            translate_path("/../../../etc/passwd")

    def test_home_traversal(self):
        with pytest.raises(PermissionError):
            translate_path("/home/agent/../../etc/shadow")

    def test_workspace_breakout(self):
        with pytest.raises(PermissionError):
            translate_path("/home/agent/workspace/../../../secret")

    def test_double_dot_in_middle(self):
        """Normalized path that stays within workspace is OK."""
        result = translate_path("/home/agent/workspace/a/b/../c")
        assert result == "workspace/a/c"

    def test_tmp_traversal(self):
        with pytest.raises(PermissionError):
            translate_path("/tmp/../etc/passwd")


class TestForbiddenPaths:
    def test_root(self):
        with pytest.raises(PermissionError):
            translate_path("/")

    def test_empty(self):
        with pytest.raises(PermissionError):
            translate_path("")

    def test_etc_passwd(self):
        with pytest.raises(PermissionError):
            translate_path("/etc/passwd")

    def test_home_without_workspace(self):
        with pytest.raises(PermissionError):
            translate_path("/home/agent/secret.txt")

    def test_relative_path(self):
        with pytest.raises(PermissionError):
            translate_path("foo.txt")

    def test_null_byte(self):
        with pytest.raises(PermissionError):
            translate_path("/home/agent/workspace/foo\x00.txt")

    def test_just_dots(self):
        with pytest.raises(PermissionError):
            translate_path("..")

    def test_home_other_user(self):
        with pytest.raises(PermissionError):
            translate_path("/home/root/.bashrc")
