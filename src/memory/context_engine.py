"""ContextEngine: builds layered system prompts from program-declared memory keys."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from brain.db.models import Program
from memory.store import MemoryStore

logger = logging.getLogger(__name__)

# Rough char-to-token ratio for budget estimation
CHARS_PER_TOKEN = 4


@dataclass
class ContextLayer:
    """A named section of the system prompt with priority and budget."""

    name: str
    content: str
    priority: int
    max_tokens: int = 0
    truncatable: bool = True

    @property
    def estimated_tokens(self) -> int:
        return len(self.content) // CHARS_PER_TOKEN


class ContextEngine:
    """Assembles layered system prompts for Bedrock converse API calls.

    Programs declare memory_keys listing which memory paths to load.
    The engine resolves those keys (with ancestor/child init expansion),
    builds priority-ordered layers, and returns Bedrock-compatible system blocks.
    """

    def __init__(self, memory_store: MemoryStore, *, total_budget: int = 50_000) -> None:
        self._memory = memory_store
        self._total_budget = total_budget

    def build_system_prompt(
        self,
        program: Program,
        event_data: dict | None = None,
    ) -> list[dict]:
        """Build system prompt as list of Bedrock text blocks.

        Layers (descending priority):
          90: Program content (never truncated)
          80: Declared memories from program.memory_keys
          70: Event context
        """
        layers: list[ContextLayer] = []

        # Layer 90: Program content
        if program.content:
            layers.append(ContextLayer(
                name="program",
                content=program.content,
                priority=90,
                truncatable=False,
            ))

        # Layer 80: Declared memories
        if program.memory_keys:
            memories = self._memory.resolve_keys(program.memory_keys)
            if memories:
                sections = []
                for mem in memories:
                    label = mem.name or "unnamed"
                    active = mem.versions.get(mem.active_version)
                    content = active.content if active else ""
                    sections.append(f"<memory name=\"{label}\">\n{content}\n</memory>")
                memory_text = "\n\n".join(sections)
                layers.append(ContextLayer(
                    name="memory",
                    content=memory_text,
                    priority=80,
                    max_tokens=30_000,
                ))

        # Layer 70: Event context
        if event_data:
            event_text = f"Event: {event_data.get('event_type', 'unknown')}"
            payload = event_data.get("payload")
            if payload:
                event_text += f"\nPayload: {json.dumps(payload, indent=2)}"
            layers.append(ContextLayer(
                name="event",
                content=event_text,
                priority=70,
                truncatable=False,
            ))

        # Sort by priority descending, apply budget
        layers.sort(key=lambda layer: layer.priority, reverse=True)
        return self._apply_budget(layers)

    def _apply_budget(self, layers: list[ContextLayer]) -> list[dict]:
        """Convert layers to Bedrock system blocks, truncating if over budget."""
        blocks: list[dict] = []
        tokens_used = 0

        for layer in layers:
            est = layer.estimated_tokens
            remaining = self._total_budget - tokens_used

            if remaining <= 0 and layer.truncatable:
                logger.info("Skipping layer %s (budget exhausted)", layer.name)
                continue

            content = layer.content
            if layer.truncatable and est > remaining:
                # Truncate to fit budget
                max_chars = remaining * CHARS_PER_TOKEN
                content = content[:max_chars] + "\n... (truncated)"
                est = remaining

            blocks.append({"text": content})
            tokens_used += est

        return blocks
