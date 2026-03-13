from unittest.mock import MagicMock

from cogos.db.models import Process, ProcessMode, ProcessStatus, Run, RunStatus
from cogos.executor import handler as executor_handler


class FakeBedrock:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
            "stopReason": "end_turn",
            "usage": {
                "inputTokens": 12,
                "outputTokens": 3,
                "totalTokens": 15,
                "cacheReadInputTokens": 9,
                "cacheWriteInputTokens": 21,
            },
        }


def _make_process() -> Process:
    return Process(
        name="discord-handle-message",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.RUNNING,
        runner="lambda",
        content="Reply to the Discord message.",
    )


def _make_run(process: Process) -> Run:
    return Run(process=process.id, status=RunStatus.RUNNING)


def test_execute_process_adds_bedrock_prompt_cache_points(monkeypatch):
    repo = MagicMock()
    process = _make_process()
    run = _make_run(process)
    bedrock = FakeBedrock()
    config = executor_handler.ExecutorConfig(prompt_cache_enabled=True, prompt_cache_ttl="1h")

    monkeypatch.setattr(executor_handler, "_setup_capability_proxies", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor_handler, "_load_includes", lambda _repo: "global include")
    monkeypatch.setattr(
        "cogos.files.context_engine.ContextEngine.generate_full_prompt",
        lambda self, _process: "process prompt",
    )

    executor_handler.execute_process(
        process,
        {"event_type": "io:discord:dm", "payload": {"content": "hello"}},
        run,
        config,
        repo,
        bedrock_client=bedrock,
    )

    request = bedrock.calls[0]
    assert request["system"] == [
        {"text": "global include\n\nprocess prompt"},
        {"cachePoint": {"type": "default", "ttl": "1h"}},
    ]
    assert request["messages"][0]["content"][-1] == {"cachePoint": {"type": "default", "ttl": "1h"}}
    assert request["toolConfig"]["tools"][-1] == {"cachePoint": {"type": "default", "ttl": "1h"}}
    assert run.tokens_in == 12
    assert run.tokens_out == 3


def test_execute_process_can_disable_prompt_cache_points(monkeypatch):
    repo = MagicMock()
    process = _make_process()
    run = _make_run(process)
    bedrock = FakeBedrock()
    config = executor_handler.ExecutorConfig(prompt_cache_enabled=False)

    monkeypatch.setattr(executor_handler, "_setup_capability_proxies", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor_handler, "_load_includes", lambda _repo: "")
    monkeypatch.setattr(
        "cogos.files.context_engine.ContextEngine.generate_full_prompt",
        lambda self, _process: "process prompt",
    )

    executor_handler.execute_process(
        process,
        {"event_type": "io:discord:dm", "payload": {"content": "hello"}},
        run,
        config,
        repo,
        bedrock_client=bedrock,
    )

    request = bedrock.calls[0]
    assert request["system"] == [{"text": "process prompt"}]
    assert request["messages"][0]["content"] == [{
        "text": "Reply to the Discord message.\n\nEvent: io:discord:dm\nPayload: {\n  \"content\": \"hello\"\n}\n"
    }]
    assert all("cachePoint" not in tool for tool in request["toolConfig"]["tools"])
