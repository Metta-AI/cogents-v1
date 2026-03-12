"""Tests that _setup_capability_proxies uses real capability classes, not inline proxies."""

from unittest.mock import MagicMock
from uuid import uuid4

from cogos.capabilities.events import EventsCapability
from cogos.capabilities.files import FilesCapability
from cogos.capabilities.procs import ProcsCapability
from cogos.capabilities.me import MeCapability
from cogos.db.models import Process, ProcessMode, ProcessStatus
from cogos.executor.handler import _setup_capability_proxies
from cogos.sandbox.executor import VariableTable


def _make_process():
    return Process(
        id=uuid4(),
        name="test-proc",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        runner="lambda",
    )


def _make_repo():
    repo = MagicMock()
    repo.list_process_capabilities.return_value = []
    return repo


class TestSetupCapabilityProxies:
    def test_files_is_real_capability(self):
        vt = VariableTable()
        _setup_capability_proxies(vt, _make_process(), _make_repo())
        assert isinstance(vt.get("files"), FilesCapability)

    def test_procs_is_real_capability(self):
        vt = VariableTable()
        _setup_capability_proxies(vt, _make_process(), _make_repo())
        assert isinstance(vt.get("procs"), ProcsCapability)

    def test_events_is_real_capability(self):
        vt = VariableTable()
        _setup_capability_proxies(vt, _make_process(), _make_repo())
        assert isinstance(vt.get("events"), EventsCapability)

    def test_me_is_real_capability(self):
        vt = VariableTable()
        _setup_capability_proxies(vt, _make_process(), _make_repo())
        assert isinstance(vt.get("me"), MeCapability)

    def test_scoped_capability_from_config(self):
        """When ProcessCapability has config, the injected instance should be scoped."""
        repo = _make_repo()
        proc = _make_process()

        pc = MagicMock()
        pc.capability = uuid4()
        pc.name = "workspace"
        pc.config = {"prefix": "/workspace/", "ops": ["list", "read"]}
        repo.list_process_capabilities.return_value = [pc]

        cap_model = MagicMock()
        cap_model.name = "files"
        cap_model.enabled = True
        cap_model.handler = "cogos.capabilities.files:FilesCapability"
        repo.get_capability.return_value = cap_model

        vt = VariableTable()
        _setup_capability_proxies(vt, proc, repo)

        workspace = vt.get("workspace")
        assert isinstance(workspace, FilesCapability)
        assert workspace._scope == {"prefix": "/workspace/", "ops": ["list", "read"]}
