"""Tests for CapabilityBridge contract — verifying the FakeBridge behaves correctly."""

import pytest

from wasm_runner.types import FetchResult


class TestFilesContract:
    @pytest.mark.asyncio
    async def test_read_missing_raises(self, bridge):
        with pytest.raises(FileNotFoundError):
            await bridge.files_read("nonexistent/key")

    @pytest.mark.asyncio
    async def test_write_then_read(self, bridge):
        await bridge.files_write("test/file.txt", b"content")
        data = await bridge.files_read("test/file.txt")
        assert data == b"content"

    @pytest.mark.asyncio
    async def test_search_returns_matching(self, bridge):
        await bridge.files_write("dir/a.txt", b"a")
        await bridge.files_write("dir/b.txt", b"b")
        await bridge.files_write("other/c.txt", b"c")
        result = await bridge.files_search("dir/")
        assert result == ["dir/a.txt", "dir/b.txt"]

    @pytest.mark.asyncio
    async def test_delete_removes_file(self, bridge):
        await bridge.files_write("del/me.txt", b"x")
        await bridge.files_delete("del/me.txt")
        with pytest.raises(FileNotFoundError):
            await bridge.files_read("del/me.txt")


class TestScopeEnforcement:
    @pytest.mark.asyncio
    async def test_prefix_enforcement(self, bridge):
        bridge.allowed_prefixes = ["allowed/"]
        await bridge.files_write("allowed/ok.txt", b"ok")
        with pytest.raises(PermissionError):
            await bridge.files_write("denied/bad.txt", b"bad")

    @pytest.mark.asyncio
    async def test_ops_enforcement(self, bridge):
        await bridge.files_write("test.txt", b"data")  # setup (before restriction)
        bridge.allowed_ops = {"read"}
        with pytest.raises(PermissionError):
            await bridge.files_write("test2.txt", b"nope")

    @pytest.mark.asyncio
    async def test_deny_all(self, bridge):
        bridge.deny_all = True
        with pytest.raises(PermissionError):
            await bridge.files_read("anything")


class TestFetchContract:
    @pytest.mark.asyncio
    async def test_fetch_canned_response(self, bridge):
        bridge.fetch_responses["https://api.test"] = FetchResult(
            status=201, body=b'{"ok": true}', headers={},
        )
        result = await bridge.web_fetch("https://api.test")
        assert result.status == 201

    @pytest.mark.asyncio
    async def test_fetch_url_denied(self, bridge):
        bridge.allowed_urls = {"https://ok.com"}
        with pytest.raises(PermissionError):
            await bridge.web_fetch("https://bad.com")


class TestCallLog:
    @pytest.mark.asyncio
    async def test_all_calls_logged(self, bridge):
        await bridge.files_write("k", b"v")
        await bridge.files_read("k")
        await bridge.files_search("k")
        await bridge.files_delete("k")
        await bridge.web_fetch("https://x.com")
        await bridge.process_spawn("cmd", [])
        await bridge.channel_send("ch", "msg")
        ops = [op for op, _ in bridge.call_log]
        assert ops == [
            "files_write", "files_read", "files_search", "files_delete",
            "web_fetch", "process_spawn", "channel_send",
        ]
