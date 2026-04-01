"""Tests for NetworkGate — proxied fetch and socket denial."""

import pytest

from wasm_runner.shim.net import NetworkGate
from wasm_runner.types import FetchResult


@pytest.fixture
def gate(bridge, audit):
    return NetworkGate(bridge, audit)


class TestAllowedFetch:
    @pytest.mark.asyncio
    async def test_fetch_returns_result(self, gate, bridge):
        bridge.fetch_responses["https://example.com"] = FetchResult(
            status=200, body=b"hello", headers={"content-type": "text/plain"},
        )
        result = await gate.fetch("https://example.com")
        assert result.status == 200
        assert result.body == b"hello"

    @pytest.mark.asyncio
    async def test_fetch_with_method(self, gate, bridge):
        result = await gate.fetch("https://api.example.com/data", method="POST", body=b'{"key": "val"}')
        assert result.status == 200

    @pytest.mark.asyncio
    async def test_fetch_default_ok(self, gate):
        """Fetch to any URL returns 200 OK when no allowlist is set."""
        result = await gate.fetch("https://anything.com")
        assert result.status == 200


class TestBlockedFetch:
    @pytest.mark.asyncio
    async def test_fetch_denied_url(self, gate, bridge):
        bridge.allowed_urls = {"https://allowed.com"}
        with pytest.raises(PermissionError, match="EPERM"):
            await gate.fetch("https://denied.com")

    @pytest.mark.asyncio
    async def test_fetch_private_ip(self, gate, bridge, audit):
        """SSRF protection: private IPs should be denied."""
        bridge.allowed_urls = {"https://public.com"}
        with pytest.raises(PermissionError):
            await gate.fetch("http://169.254.169.254/latest/meta-data")

    @pytest.mark.asyncio
    async def test_fetch_localhost(self, gate, bridge):
        bridge.allowed_urls = {"https://public.com"}
        with pytest.raises(PermissionError):
            await gate.fetch("http://localhost:8080/secret")


class TestSocketDenial:
    @pytest.mark.asyncio
    async def test_raw_tcp_denied(self, gate):
        with pytest.raises(PermissionError, match="EPERM.*TCP"):
            await gate.raw_tcp("example.com", 80)

    @pytest.mark.asyncio
    async def test_raw_udp_denied(self, gate):
        with pytest.raises(PermissionError, match="EPERM.*UDP"):
            await gate.raw_udp("example.com", 53)
