"""Tests for memory.context_engine.ContextEngine."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from brain.db.models import MemoryRecord, MemoryScope, Program, ProgramType
from memory.context_engine import CHARS_PER_TOKEN, ContextEngine


@pytest.fixture
def memory_store():
    return MagicMock()


@pytest.fixture
def engine(memory_store):
    return ContextEngine(memory_store, total_budget=50_000)


def _program(content: str = "", memory_keys: list[str] | None = None) -> Program:
    return Program(
        name="test-program",
        program_type=ProgramType.PROMPT,
        content=content,
        memory_keys=memory_keys or [],
    )


def _rec(name: str, content: str = "") -> MemoryRecord:
    return MemoryRecord(scope=MemoryScope.COGENT, name=name, content=content or f"content of {name}")


class TestProgramContentOnly:
    def test_single_text_block(self, engine, memory_store):
        blocks = engine.build_system_prompt(_program("You are a helpful bot."))

        assert len(blocks) == 1
        assert blocks[0]["text"] == "You are a helpful bot."
        memory_store.resolve_keys.assert_not_called()


class TestProgramWithMemoryKeys:
    def test_memories_wrapped_in_tags(self, engine, memory_store):
        memory_store.resolve_keys.return_value = [
            _rec("/mind/init", "base personality"),
            _rec("/mind/tools/init", "tool instructions"),
        ]

        blocks = engine.build_system_prompt(
            _program("System prompt.", memory_keys=["/mind/tools"])
        )

        assert len(blocks) == 2
        # First block is program (priority 90)
        assert blocks[0]["text"] == "System prompt."
        # Second block is memories (priority 80)
        assert '<memory name="/mind/init">' in blocks[1]["text"]
        assert "base personality" in blocks[1]["text"]
        assert '<memory name="/mind/tools/init">' in blocks[1]["text"]


class TestProgramWithEvent:
    def test_event_appended(self, engine, memory_store):
        blocks = engine.build_system_prompt(
            _program("Prompt."),
            event_data={"event_type": "message", "payload": {"text": "hi"}},
        )

        assert len(blocks) == 2
        assert blocks[0]["text"] == "Prompt."
        assert "Event: message" in blocks[1]["text"]
        assert '"text": "hi"' in blocks[1]["text"]


class TestAllThreeLayers:
    def test_ordering_program_memory_event(self, engine, memory_store):
        memory_store.resolve_keys.return_value = [_rec("/m")]

        blocks = engine.build_system_prompt(
            _program("Program.", memory_keys=["/m"]),
            event_data={"event_type": "tick"},
        )

        assert len(blocks) == 3
        # Priority order: 90 (program), 80 (memory), 70 (event)
        assert blocks[0]["text"] == "Program."
        assert '<memory name="/m">' in blocks[1]["text"]
        assert "Event: tick" in blocks[2]["text"]


class TestEmptyProgramContent:
    def test_skipped(self, engine, memory_store):
        blocks = engine.build_system_prompt(_program(""))

        assert len(blocks) == 0


class TestBudgetTruncation:
    def test_memory_truncated_when_exceeding_budget(self, memory_store):
        # Small budget: 100 tokens = 400 chars
        engine = ContextEngine(memory_store, total_budget=100)
        long_content = "x" * 800  # 200 tokens, exceeds remaining after program

        memory_store.resolve_keys.return_value = [_rec("/big", long_content)]

        blocks = engine.build_system_prompt(
            _program("Short.", memory_keys=["/big"]),
        )

        # Program is non-truncatable, takes ~2 tokens
        # Memory should be truncated
        memory_block = blocks[1]["text"]
        assert memory_block.endswith("... (truncated)")
        assert len(memory_block) < len(long_content)


class TestBudgetExhaustion:
    def test_truncatable_layer_skipped_when_budget_used(self, memory_store):
        # Budget of 10 tokens = 40 chars; program "x"*40 = 10 tokens, uses it all
        engine = ContextEngine(memory_store, total_budget=10)
        memory_store.resolve_keys.return_value = [_rec("/m", "some memory")]

        blocks = engine.build_system_prompt(
            _program("x" * 40, memory_keys=["/m"]),
        )

        # Only program block should be present; memory skipped
        assert len(blocks) == 1
        assert blocks[0]["text"] == "x" * 40


class TestMemoryDedupViaStore:
    def test_resolve_keys_called_with_program_keys(self, engine, memory_store):
        memory_store.resolve_keys.return_value = []

        engine.build_system_prompt(
            _program("P.", memory_keys=["/a", "/b/c"]),
        )

        memory_store.resolve_keys.assert_called_once_with(["/a", "/b/c"])
