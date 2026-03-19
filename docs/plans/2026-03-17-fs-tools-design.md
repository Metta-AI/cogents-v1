# File System Tools Design

Extend `dir` and `file` capabilities to support grep, glob, tree, line-sliced reads, and surgical edits — making cogware as powerful as Claude Code's shell tools, backed by RDS.

## New Methods

### dir capability

**`dir.grep(pattern, prefix=None, limit=20, context=0)`**
- Regex search across file contents (Postgres `~` operator)
- `prefix`: narrows within dir's scoped prefix
- `limit`: max total matches across all files
- `context`: lines before/after each match (like `grep -C`)
- Returns: `[{"key": "src/main.py", "matches": [{"line": 42, "text": "# TODO fix", "before": [...], "after": [...]}]}, ...]`
- Scope-enforced: only searches within dir's prefix

**`dir.glob(pattern, limit=50)`**
- Glob pattern matching on file keys: `*` = one segment, `**` = any depth, `?` = single char
- Translated to Postgres regex
- Returns: `[{"key": "src/config.yaml"}, ...]`
- Scope-enforced: filtered to dir's prefix

**`dir.tree(prefix=None, depth=3)`**
- Compact tree string of keys grouped by path segments
- Respects depth limit
- Useful for orientation

### file capability

**`file.read(key, offset=None, limit=None)`** (extended)
- Optional 0-indexed line-based slicing
- Returns `FileContent` with added `total_lines` field
- When sliced, `content` contains only requested lines

**`file.head(key, n=20)`**
- Sugar for `read(key, offset=0, limit=n)`

**`file.tail(key, n=20)`**
- Sugar for `read(key, offset=-n)`

**`file.edit(key, old, new, replace_all=False)`**
- Exact string replacement in current content
- `replace_all=False`: fails if `old` not found or not unique
- `replace_all=True`: replaces all occurrences, fails if zero matches
- Returns `FileWriteResult` (new version created)

## DB Layer

### Content search (dir.grep)
```sql
SELECT f.key, fv.content
FROM cogos_file f
JOIN cogos_file_version fv ON fv.file_id = f.id
WHERE fv.is_active = true
  AND f.key LIKE :prefix || '%'
  AND fv.content ~ :pattern
LIMIT 100
```
Line splitting, context extraction, and match limiting in Python.

### Glob matching (dir.glob)
Translate glob to Postgres regex:
- `*` → `[^/]*`
- `**` → `.*`
- `?` → `.`

```sql
SELECT f.key FROM cogos_file f
WHERE f.key ~ :glob_as_regex
  AND f.key LIKE :scoped_prefix || '%'
```

### Line-sliced read
No DB change. Fetch full content, split on `\n` in Python, return slice. Savings are in tokens sent to LLM, not DB bandwidth.

**No new tables or columns.**

## Registry & Scope

- `dir` ops enum: add `"grep"`, `"glob"`, `"tree"`
- `file` ops enum: add `"edit"`
- `file.read` schema: add `offset`/`limit` params
- Scope enforcement unchanged — grep/glob/tree respect `prefix`, edit respects `key` + `ops`

## Capability Instructions Include

A file included in cogware system prompts via `@{fs-tools}`:

```markdown
# File System

## Finding files
- `dir.grep(pattern, prefix?, limit=20, context=0)` — regex search file contents. Returns keys + matching lines with line numbers.
- `dir.glob(pattern, limit=50)` — match file keys by glob pattern. `*`=one segment, `**`=any depth.
- `dir.tree(prefix?, depth=3)` — compact directory tree.
- `dir.list(prefix?, limit=50)` — list file keys by prefix.

## Reading files
- `file.read(key, offset?, limit?)` — read file. offset/limit are 0-indexed line numbers. Returns content + total_lines.
- `file.head(key, n=20)` — first n lines.
- `file.tail(key, n=20)` — last n lines.

## Editing files
- `file.edit(key, old, new, replace_all=False)` — exact string replacement. Fails if old not found (or not unique unless replace_all=True).
- `file.write(key, content)` — overwrite entire file.
- `file.append(key, content)` — append to file.

## Patterns
- Explore then act: `dir.tree()` → `dir.grep(pattern)` → `file.read(key, offset, limit)` → `file.edit(key, old, new)`
- Bulk rename: `for m in dir.grep("old_name"): file.edit(m["key"], "old_name", "new_name", replace_all=True)`
- Large file: check size with `file.read(key, limit=1)` (see total_lines), then slice what you need
```

## What we're NOT building

Python in `run_code` already covers:
- Complex transforms (regex substitution, reformatting, parsing)
- Multi-file edits in a loop
- Diffing files (`difflib`)
- JSON/YAML/CSV parsing
- String counting, extraction, splitting
