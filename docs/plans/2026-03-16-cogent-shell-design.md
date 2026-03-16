# Cogent Shell Design

Interactive Unix-like shell for managing a cogent's CogOS instance.

```
cogent dr.alpha shell
```

## Architecture

A `prompt_toolkit` interactive session connected to a cogent's CogOS database. Presents a virtual filesystem over the versioned file store, process management via Unix idioms, and direct access to channels, capabilities, and runs.

### Shell State

- `cwd: str` — current prefix in the file store (starts at `/`)
- `repo: Repository` — CogOS database connection
- `cogent_name: str` — which cogent we're connected to
- `bedrock_client` — for `llm` command execution

### Prompt

```
dr.alpha:/config/prompts$
```

Bottom toolbar (refreshes per command):
```
 procs: 3 running, 2 waiting | files: 47 | caps: 12 enabled | last run: 2m ago (scheduler, 1.2s)
```

## Command Reference

### File Commands (resolve relative to cwd)

| Command | Description |
|---------|-------------|
| `ls [path]` | List files/subdirs at path (or cwd) |
| `cd <path>` | Change directory (supports `.`, `..`, absolute) |
| `pwd` | Print working directory |
| `tree [path]` | Recursive listing |
| `cat <file>` | Print file content |
| `less <file>` | Page through system pager |
| `rm <file>` | Delete file from store |
| `mkdir <path>` | No-op (dirs are implicit from key prefixes) |
| `vim <file>` / `edit <file>` | Pull to tmpfile, open `$EDITOR`, write back if changed |

### Process Commands

| Command | Description |
|---------|-------------|
| `ps [--all]` | List processes (default: non-completed) |
| `kill <name>` | Disable process |
| `kill -9 <name>` | Disable + clear context |
| `kill -HUP <name>` | Restart (mark runnable) |
| `spawn <name> [--content "..."] [--runner lambda\|ecs] [--model ...]` | Create and queue a process |
| `top` | Live-refreshing process table |

### Channel Commands

| Command | Description |
|---------|-------------|
| `ch ls` | List channels |
| `ch send <channel> <payload>` | Send a message |
| `ch log <channel> [--limit N]` | Show recent messages |

### Capability Commands

| Command | Description |
|---------|-------------|
| `cap ls` | List capabilities |
| `cap enable <name>` | Enable a capability |
| `cap disable <name>` | Disable a capability |

### Run Commands

| Command | Description |
|---------|-------------|
| `runs [--process name] [--limit N]` | List recent runs |
| `run show <id>` | Show run detail |

### LLM Execution

| Command | Description |
|---------|-------------|
| `llm <prompt>` | One-shot prompt via Bedrock with all capabilities |
| `llm -f <file>` | One-shot, file content as prompt |
| `llm -i` | Interactive multi-turn session |
| `llm -i -f <file>` | Interactive with file as initial context |
| `source <file>` / `. <file>` | Sugar for `llm -f <file>` |

Execution model:
1. Create temporary process `shell-<timestamp>` in DB
2. Grant all enabled capabilities
3. Call `run_and_complete()` from `cogos.runtime.local`
4. Stream output to shell, show tool calls inline with dim prefix
5. Show token usage and duration on completion
6. In `-i` mode: loop until ctrl+d or `/exit`

Tool call display:
```
[files.search] prefix="prompts/" -> 4 results
```

### Shell Builtins

| Command | Description |
|---------|-------------|
| `help [command]` | Show help |
| `clear` | Clear screen |
| `exit` / ctrl+d | Quit |

## Tab Completion

Context-aware `prompt_toolkit` completer:

- **First token**: command names
- **File commands** (`cat`, `ls`, `cd`, etc.): file paths/directory prefixes relative to cwd
- **Process commands** (`kill`, `spawn`): process names
- **Channel commands** (`ch send`, `ch log`): channel names
- **Capability commands** (`cap enable/disable`): capability names
- **`runs --process`**: process names
- **`spawn --runner`**: `lambda`, `ecs`

File path completion: splits on `/`, resolves against cwd, queries `repo.list_files(prefix=...)`, deduplicates at path segment level to show directories vs files.

Lazy query with short cache TTL to avoid hammering DB on rapid tab presses.

## Colors

- Cogent name: bold cyan
- Path: white
- `ls` directories: bold blue, files: white
- Process status: green=running, yellow=waiting/runnable, red=disabled

## Module Structure

```
src/cogos/shell/
  __init__.py          # CogentShell class, main loop, prompt setup
  completer.py         # Context-aware tab completer
  commands/
    __init__.py        # Command registry + dispatch
    files.py           # ls, cd, pwd, tree, cat, less, rm, vim/edit
    procs.py           # ps, kill, spawn, top
    channels.py        # ch ls, ch send, ch log
    caps.py            # cap ls, cap enable, cap disable
    runs.py            # runs, run show
    llm.py             # llm, source, .
    builtins.py        # help, clear, exit
```

## Entry Point

In `src/cli/__main__.py`:
- Add `"shell"` to `_COMMANDS` set
- Register `shell` command on `main` group
- Shell command imports `CogentShell` and calls `.run()`

## Dependencies

- `prompt_toolkit` added to `pyproject.toml`
