# Integrating the Agentica Pattern into Cogents

**Date**: 2026-03-08
**Status**: Proposal
**References**:
- [Beyond Code Mode: Agentica (Symbolica Blog)](https://www.symbolica.ai/blog/beyond-code-mode-agentica)
- [Agentica Python SDK](https://github.com/symbolica-ai/agentica-python-sdk)
- [Agentica Docs](https://docs.symbolica.ai)

---

## What is the Agentica Pattern?

Symbolica's Agentica framework is built on a core thesis: **code is the most expressive interface through which LLM agents can interact with their environment**. Rather than constraining agents to JSON tool schemas, you give them live typed objects to write code against.

Three key ideas:

1. **Scope-based capability discovery** — Agents receive real objects (DB connections, SDK clients, functions) in their "scope." They discover capabilities through the methods those objects expose. The scope grows as methods return new objects — no upfront registration needed.

2. **Code-as-interface** — Instead of selecting tools from a JSON schema, the agent writes and executes actual code against scope objects. This handles sequential method calls, conditional logic, and compositions that are awkward to express as flat tool schemas.

3. **On-demand definition inspection** — Agents can `show_definition` on any object in scope (analogous to CMD+Click / go-to-definition), pulling type signatures and docstrings into context only when needed rather than front-loading everything.

Results: GPT-5 scored 77.11% on BrowseComp-Plus with Agentica vs 73.25% without. The pattern also achieved 85.28% on ARC-AGI-2.

---

## Current Cogents Architecture (Status Quo)

```
EventBridge event
  → Orchestrator Lambda (trigger matching)
    → Executor Lambda/ECS (program execution)
      → Bedrock converse API (tool-use loop)
        → Static JSON tool schemas (memory_get, memory_put, event_send, gmail_*)
```

Key characteristics of the current system:

| Aspect | Current Cogents | Agentica Pattern |
|--------|----------------|------------------|
| **Tool interface** | Static JSON schemas in `TOOL_SCHEMAS` dict | Typed objects in scope |
| **Discovery** | All tools listed upfront in `_build_tool_config()` | Progressive, on-demand via `show_definition` |
| **Execution** | Bedrock tool_use → `_execute_tool()` dispatch | Agent writes + runs code against live objects |
| **Composition** | Programs can emit events to chain other programs | Agents spawn sub-agents; objects return objects |
| **Type safety** | None (string in, string out for all tools) | Return types enforced at runtime |
| **Context mgmt** | `ContextEngine` with priority layers | Objects themselves manage context |

---

## Integration Proposal

The proposal is NOT to replace the current system wholesale, but to introduce a **new program type** (`ProgramType.AGENTIC`) alongside the existing `PROMPT` and `PYTHON` types. This is additive — existing programs keep working unchanged.

### Phase 1: Scope Registry & Typed Tools

**Goal**: Replace the flat `TOOL_SCHEMAS` dict with a scope-based object registry that programs can selectively pull from.

#### 1a. Define a `Scope` abstraction

```python
# src/brain/scope.py

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, get_type_hints
import inspect

@dataclass
class ScopeObject:
    """A typed object available to an agent."""
    name: str
    obj: Any
    type_hint: type | None = None
    description: str = ""
    methods: dict[str, MethodSpec] = field(default_factory=dict)

@dataclass
class MethodSpec:
    """Introspected method signature for context injection."""
    name: str
    params: dict[str, str]      # param_name -> type annotation string
    return_type: str
    docstring: str

class Scope:
    """A namespace of typed objects an agent can interact with."""

    def __init__(self) -> None:
        self._objects: dict[str, ScopeObject] = {}

    def add(self, name: str, obj: Any, *, description: str = "") -> None:
        """Register an object into scope with introspected methods."""
        methods = {}
        for method_name, method in inspect.getmembers(obj, predicate=inspect.ismethod):
            if method_name.startswith("_"):
                continue
            hints = get_type_hints(method)
            params = {
                k: str(v) for k, v in hints.items() if k != "return"
            }
            methods[method_name] = MethodSpec(
                name=method_name,
                params=params,
                return_type=str(hints.get("return", "Any")),
                docstring=inspect.getdoc(method) or "",
            )
        self._objects[name] = ScopeObject(
            name=name, obj=obj, description=description, methods=methods,
        )

    def get(self, name: str) -> Any:
        entry = self._objects.get(name)
        return entry.obj if entry else None

    def list_names(self) -> list[str]:
        return list(self._objects.keys())

    def show_definition(self, name: str) -> str:
        """Return a human/LLM-readable definition of an object and its methods."""
        entry = self._objects.get(name)
        if not entry:
            return f"Object '{name}' not found in scope."
        lines = [f"## {name}", ""]
        if entry.description:
            lines.append(entry.description)
            lines.append("")
        for m in entry.methods.values():
            sig_parts = [f"{k}: {v}" for k, v in m.params.items()]
            lines.append(f"### {m.name}({', '.join(sig_parts)}) -> {m.return_type}")
            if m.docstring:
                lines.append(m.docstring)
            lines.append("")
        return "\n".join(lines)

    def to_summary(self) -> str:
        """One-line-per-object summary for initial context."""
        lines = ["Available objects in scope:"]
        for name, entry in self._objects.items():
            method_names = list(entry.methods.keys())
            lines.append(f"  - {name}: {entry.description or 'no description'} "
                         f"[methods: {', '.join(method_names[:5])}{'...' if len(method_names) > 5 else ''}]")
        lines.append("")
        lines.append("Use show_definition(name) to inspect any object's full API.")
        return "\n".join(lines)
```

#### 1b. Wrap existing capabilities as scope objects

Create typed wrapper classes for the core capabilities agents currently access via flat tools:

```python
# src/brain/scope_objects.py

class MemoryScope:
    """Typed memory operations."""

    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    def get(self, key: str) -> str | None:
        """Retrieve memory content by key name."""
        results = self._repo.query_memory(name=key)
        return results[0].content if results else None

    def put(self, key: str, value: str, *, read_only: bool = False) -> str:
        """Store a value under a key name. Returns confirmation."""
        ...

    def list(self, prefix: str = "") -> list[str]:
        """List memory keys matching prefix."""
        ...

class EventBus:
    """Typed event emission."""

    def __init__(self, bus_name: str) -> None: ...

    def send(self, event_type: str, payload: dict | None = None) -> int:
        """Send an event. Returns event ID."""
        ...

class TaskQueue:
    """Task management operations."""

    def __init__(self, repo: Repository) -> None: ...

    def list_runnable(self, limit: int = 20) -> list[dict]:
        """List runnable tasks with id, name, priority."""
        ...

    def complete(self, task_id: str) -> str:
        """Mark a task as completed."""
        ...
```

#### 1c. Programs declare scope objects instead of tool names

Extend `CogentMindProgram` and frontmatter to support `scope`:

```yaml
---
program_type: agentic
scope:
  - memory
  - events
  - tasks
  - gmail          # Channel-specific scope objects loaded on demand
---
You are executing a task. Objects in your scope let you interact with
memory, events, and tasks. Use show_definition() to inspect their APIs.
```

### Phase 2: Code Execution Mode

**Goal**: Let agentic programs write and execute code against scope objects instead of using the JSON tool-use loop.

#### 2a. Add `ProgramType.AGENTIC`

```python
class ProgramType(str, enum.Enum):
    PROMPT = "prompt"      # Existing: system prompt → Bedrock converse tool-use loop
    PYTHON = "python"      # Existing: static Python script with run() function
    AGENTIC = "agentic"    # New: LLM writes code against typed scope objects
```

#### 2b. Agentic executor loop

The key difference from the current `execute_program()`:

```
Current (PROMPT):
  system prompt + tools → converse() → tool_use stop → _execute_tool() → loop

Proposed (AGENTIC):
  system prompt + scope summary → converse() → code block stop → sandbox_exec() → loop
```

```python
# src/brain/lambdas/executor/agentic.py

def execute_agentic_program(program, event_data, run, config, task_data=None):
    """Execute program where the LLM writes code against scope objects."""
    scope = build_scope(program, config)

    # System prompt: program content + scope summary
    system = [
        {"text": program.content},
        {"text": scope.to_summary()},
        {"text": AGENTIC_INSTRUCTIONS},  # How to write code, show_definition, etc.
    ]

    # The LLM gets one special tool: execute_code and show_definition
    tool_config = {
        "tools": [
            {"toolSpec": {
                "name": "execute_code",
                "description": "Execute Python code against scope objects. "
                               "Available variables: " + ", ".join(scope.list_names()),
                "inputSchema": {"json": {
                    "type": "object",
                    "properties": {"code": {"type": "string"}},
                    "required": ["code"],
                }},
            }},
            {"toolSpec": {
                "name": "show_definition",
                "description": "Inspect an object's full API (methods, params, return types).",
                "inputSchema": {"json": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                }},
            }},
        ]
    }

    # Converse loop — same structure as current, but tool execution runs code
    for _turn in range(max_turns):
        response = bedrock.converse(modelId=model_id, messages=messages,
                                    system=system, toolConfig=tool_config)
        ...
        if stop_reason == "tool_use":
            for block in output_message["content"]:
                if block.get("toolUse", {}).get("name") == "execute_code":
                    code = block["toolUse"]["input"]["code"]
                    result = sandbox_exec(code, scope)
                    ...
                elif block.get("toolUse", {}).get("name") == "show_definition":
                    name = block["toolUse"]["input"]["name"]
                    result = scope.show_definition(name)
                    ...
```

#### 2c. Sandboxed execution

Code runs in a restricted namespace containing only scope objects:

```python
def sandbox_exec(code: str, scope: Scope, *, timeout_seconds: int = 30) -> str:
    """Execute agent-written code with only scope objects available."""
    namespace = {}
    for name in scope.list_names():
        namespace[name] = scope.get(name)
    # Also inject show_definition
    namespace["show_definition"] = scope.show_definition

    # RestrictedPython or similar for safety, or rely on ECS container isolation
    try:
        exec(compile(code, "<agent-code>", "exec"), {"__builtins__": SAFE_BUILTINS}, namespace)
    except Exception as e:
        return f"Error: {e}"

    # Capture return value via convention (agent sets `result = ...`)
    return str(namespace.get("result", "Code executed successfully."))
```

For **Lambda execution** (lightweight), use RestrictedPython with a curated `SAFE_BUILTINS` set. For **ECS execution** (heavy compute), the container isolation already provides sandboxing — can allow fuller Python.

### Phase 3: Progressive Discovery & Return-Type Objects

**Goal**: When a scope method returns a complex object, that object automatically enters scope — enabling multi-step discovery without upfront registration.

```python
class Scope:
    def execute_and_capture(self, code: str) -> str:
        """Execute code; if it returns a typed object, add to scope."""
        ...
        result = eval(...)
        if hasattr(result, '__class__') and not isinstance(result, (str, int, float, bool)):
            self.add(f"_result_{len(self._objects)}", result,
                     description=f"Returned from previous code execution")
        ...
```

Example flow:
1. Agent has `tasks` in scope
2. Agent calls `task = tasks.get("abc-123")` — returns a `TaskDetail` object
3. `TaskDetail` auto-enters scope, agent can now call `task.update_status("completed")`

This mirrors Agentica's core insight: scope grows organically as the agent explores.

### Phase 4: Multi-Agent Composition

**Goal**: Agentic programs can spawn sub-agents, with scope inheritance.

```python
class AgentSpawner:
    """Available in scope as 'spawn'. Creates sub-agents."""

    async def spawn(self, premise: str, scope_names: list[str],
                    return_type: str = "str") -> str:
        """Spawn a sub-agent with a subset of the current scope."""
        ...
```

This maps naturally to cogent's existing ability to emit `task:run` events, but adds the ability to pass a focused scope subset and enforce a return type.

---

## Architecture Comparison

```
CURRENT:
  Event → Orchestrator → Executor
           ↓                ↓
       Trigger match    Bedrock converse()
                            ↓
                        tool_use stop → _execute_tool(name, input) → hardcoded switch
                            ↓
                        end_turn stop → done

WITH AGENTIC:
  Event → Orchestrator → Executor
           ↓                ↓
       Trigger match    Build Scope from program.scope declarations
                            ↓
                        Bedrock converse() with scope summary in system prompt
                            ↓
                        tool_use stop → execute_code(code) → sandbox_exec(code, scope)
                            ↓                                    ↓
                        show_definition(name) → scope.show_definition()
                            ↓
                        end_turn stop → done
```

---

## What Changes, What Stays

| Component | Change? | Details |
|-----------|---------|---------|
| `ProgramType` enum | **Add** `AGENTIC` | Backward compatible |
| `TOOL_SCHEMAS` dict | **Keep** | Still used by `PROMPT` programs |
| `_execute_tool()` | **Keep** | Still used by `PROMPT` programs |
| `execute_program()` | **Keep** | Unchanged for `PROMPT` programs |
| `execute_python_program()` | **Keep** | Unchanged for `PYTHON` programs |
| Executor handler | **Extend** | Add branch for `AGENTIC` type |
| `ContextEngine` | **Extend** | Add scope summary as a context layer |
| `CogentMindProgram` | **Extend** | Add optional `scope` field |
| Program frontmatter | **Extend** | Support `scope:` list |
| New: `Scope` class | **Add** | Core new abstraction |
| New: scope objects | **Add** | Typed wrappers (MemoryScope, EventBus, etc.) |
| New: `sandbox_exec` | **Add** | Code execution sandbox |
| Orchestrator | **No change** | Dispatches same as today |
| Database models | **No change** | Run/Trace/Event unchanged |
| EventBridge flow | **No change** | Same trigger → dispatch pipeline |

---

## Implementation Order

1. **`Scope` + `ScopeObject` classes** — Pure data structures, no side effects, fully testable
2. **Scope object wrappers** — `MemoryScope`, `EventBus`, `TaskQueue` wrapping existing `Repository`
3. **`sandbox_exec`** — Code execution with restricted builtins
4. **`ProgramType.AGENTIC`** + executor branch — Wire it into the executor handler
5. **Program loader** — Parse `scope:` from frontmatter/`CogentMindProgram`
6. **Progressive discovery** — Auto-register returned objects
7. **Multi-agent spawning** — Sub-agent creation from scope

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| **Code injection / sandbox escape** | RestrictedPython for Lambda; container isolation for ECS; curated `SAFE_BUILTINS`; no `import`, `open`, `eval` in builtins |
| **Runaway execution** | Timeout on `sandbox_exec`; same `max_turns` limit as current loop |
| **Token cost inflation** | `show_definition` is on-demand (not all defs loaded upfront); scope summary is compact |
| **Complexity creep** | Phases are independent; Phase 1 alone (typed scope objects) adds value even without code execution |
| **Model capability** | Claude Sonnet generates reliable Python; test with current Bedrock models first |

---

## Why This Fits Cogents

1. **VSM alignment** — The Viable System Model already separates concerns (body/brain/mind/memory/channels). Scope objects are the natural typed interface between the brain (executor) and the other subsystems. Today `_execute_tool()` is a flat switch statement; scope objects make each subsystem a first-class citizen.

2. **Programs already have two types** — Adding `AGENTIC` follows the established pattern. Python programs already execute code via `exec()`; agentic programs extend this by letting the LLM write the code.

3. **Event-driven architecture preserved** — The orchestrator/trigger/dispatch pipeline is untouched. Agentic programs still emit events, complete tasks, and read memory — they just do it through typed objects instead of JSON tool schemas.

4. **Progressive capability** — A program can start as `PROMPT` for simple tasks, graduate to `AGENTIC` when it needs richer tool composition, without changing the surrounding infrastructure.
