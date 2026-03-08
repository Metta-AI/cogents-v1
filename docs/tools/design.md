# Tools as a First-Class Datatype

## Overview

Elevate tools from hardcoded Python dicts to a first-class entity stored in the database, editable via the dashboard, and referenced by programs and tasks. When a task or program runs, all referenced tools are included as Bedrock tool specs and their usage instructions are injected into the system prompt.

## Tool Data Model

New `Tool` pydantic model in `src/brain/db/models.py`:

```python
class Tool(BaseModel):
    id: UUID
    name: str           # hierarchical, e.g. "mind/task/create"
    description: str    # short description for Bedrock toolSpec
    instructions: str   # usage guidance injected into system prompt
    input_schema: dict  # JSON Schema for tool parameters
    handler: str        # Python dotted path, e.g. "brain.tools.mind.dispatch"
    enabled: bool = True
    metadata: dict = {}
    created_at: datetime | None
    updated_at: datetime | None
```

- `name` is hierarchical with `/` separators, derived from file path when loaded from disk.
- `handler` is a dotted Python path to a function with signature `(tool_name: str, tool_input: dict, config) -> str`.
- `instructions` is free-text guidance assembled into the system prompt when the tool is active.

New `tools` table in `src/brain/db/schema.sql` with the same fields, indexed on `name`.

## Execution Integration

Replaces the hardcoded `TOOL_SCHEMAS` dict and `if/elif` chain in `src/brain/lambdas/executor/handler.py`.

### New flow

1. **Collect tool names** — union of `program.tools` + `task.tools` (already exists).
2. **Load tool definitions from DB** — `repo.get_tools(names)` fetches all referenced `Tool` records.
3. **Build Bedrock toolSpec** — from each tool's `name`, `description`, and `input_schema`.
4. **Inject instructions into system prompt** — `ContextEngine` appends a `## Available Tools` section:

```
## Available Tools

### mind/task/create
Use this tool to create a new task. Tasks are work items that
reference a program and get scheduled for execution.
Always provide a descriptive name and a valid program_name.

### memory/get
Retrieve a memory value by key. Use exact key names from the memory list.
```

5. **Dispatch tool calls** — `_execute_tool()` dynamically imports the handler function from `tool.handler` and calls it. The hardcoded `if/elif` chain is removed.

## File Format and Directory Structure

Tool definitions live in `eggs/ovo/tools/` as `.py` files exporting a `Tool` pydantic model instance. The tool `name` is derived from the file path relative to `eggs/ovo/tools/`.

### Directory layout

```
eggs/ovo/tools/
  mind/
    task/
      create.py
      list.py
      update.py
      disable.py
      enable.py
    trigger/
      create.py
      list.py
      enable.py
      disable.py
      delete.py
    event/
      send.py
      list.py
    memory/
      get.py
      put.py
      list.py
    program/
      list.py
      info.py
      disable.py
    cron/
      create.py
      list.py
      enable.py
      disable.py
      delete.py
    resource/
      list.py
      add.py
      delete.py
  channels/
    gmail/
      send.py
      check.py
```

### File format

Each `.py` file exports a `tool` attribute:

```python
from brain.db.models import Tool

tool = Tool(
    description="Create a new task in the work queue",
    handler="brain.tools.mind.dispatch",
    instructions="""
Use this tool to create a new task. Tasks are work items that
reference a program and get scheduled for execution.
Always provide a descriptive name and a valid program_name.
""",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Unique task name"},
            "program_name": {"type": "string", "description": "Program to run"},
            "content": {"type": "string", "description": "Task content/instructions"},
            "priority": {"type": "number", "description": "Higher priority runs first (default 0)"},
        },
        "required": ["name", "program_name"],
    },
)
```

The loader walks the directory tree, imports each `.py` file, reads the `tool` attribute, and derives the name from the path (e.g., `mind/task/create.py` -> `mind/task/create`).

## Auto-generating Mind CLI Tools

A generator introspects the click command tree in `src/mind/cli.py` and produces tool definition `.py` files.

For each command like `cogent mind task create`:

- **name**: `mind/task/create` (from click group/command hierarchy)
- **description**: from click command help text
- **input_schema**: derived from `@click.option` and `@click.argument` — each becomes a JSON Schema property with type, description, required, enum, defaults
- **instructions**: auto-generated from docstring + parameter help strings, editable after generation
- **handler**: all point to `brain.tools.mind.dispatch` which maps tool names to repository methods

The handler implementation calls repo methods directly (no subprocess). For example `mind/task/create` calls `repo.insert_task(Task(...))`, `mind/trigger/list` calls `repo.list_triggers()`.

Invoked via:
```
cogent mind tool generate-mind-tools
```

## Mind CLI

New `tool` subgroup under `cogent mind`:

- `cogent mind tool list` — list all tools
- `cogent mind tool show <name>` — show tool details
- `cogent mind tool update [path]` — sync files from `eggs/ovo/tools/` to DB
- `cogent mind tool enable <name>`
- `cogent mind tool disable <name>`
- `cogent mind tool generate-mind-tools` — auto-generate from click introspection

## Dashboard

New **Tools** tab using the existing `HierarchyPanel` tree view component.

### Left panel (tree view)

Hierarchy showing `mind/`, `mind/task/`, `mind/trigger/`, `channels/`, `channels/gmail/`, etc. Clicking a folder filters to tools in that subtree. Individual tools appear as leaves under their folder node.

### Right panel

When no tool is selected: table of tools in the current group — name, description, enabled/disabled badge, handler. Click a row to select.

### Detail view (tool selected)

- Name, description, enabled toggle
- Handler path
- Instructions (rendered markdown, editable)
- Input schema (pretty-printed JSON, editable)
- **Referenced by** — programs and tasks whose `tools` array contains this tool name (reverse lookup answering "what breaks if I disable this?")

### Backend API

New router `src/dashboard/routers/tools.py`:

- `GET /tools` — list all, supports `?prefix=mind/task`
- `GET /tools/{name}` — detail + reverse references
- `PUT /tools/{name}` — update instructions/schema/enabled
- `DELETE /tools/{name}`

## Implementation Scope

| # | Area | Files |
|---|------|-------|
| 1 | Data model | `src/brain/db/models.py` — new `Tool` model |
| 2 | Database | `src/brain/db/schema.sql` — new `tools` table |
| 3 | Repository | `src/brain/db/repository.py` — CRUD: `insert_tool`, `get_tool`, `list_tools`, `get_tools(names)`, `update_tool`, `delete_tool` |
| 4 | Tool loader | `src/mind/tool_loader.py` — walk `eggs/ovo/tools/`, import `.py` files, derive name from path, `sync_tools()` |
| 5 | CLI tool generator | `src/mind/tool_generator.py` — introspect click tree, write `.py` files to `eggs/ovo/tools/mind/` |
| 6 | Tool handlers | `src/brain/tools/mind.py` — `dispatch()` for mind CLI tools; migrate `memory_get`, `memory_put`, `event_send`, gmail into handler files |
| 7 | Executor | `src/brain/lambdas/executor/handler.py` — `_build_tool_config()` loads from DB; `_execute_tool()` dynamically imports handler; tool instructions injected into system prompt via `ContextEngine` |
| 8 | Mind CLI | `src/mind/cli.py` — new `tool` subgroup: `list`, `show`, `update`, `enable`, `disable`, `generate-mind-tools` |
| 9 | Dashboard backend | `src/dashboard/routers/tools.py` — REST endpoints + reverse reference lookup |
| 10 | Dashboard frontend | `dashboard/frontend/src/components/tools/ToolsPanel.tsx` — tree view, detail view with editing, referenced-by section |
| 11 | Tool definitions | `eggs/ovo/tools/mind/**/*.py`, `eggs/ovo/tools/channels/**/*.py` — auto-generated + migrated |
