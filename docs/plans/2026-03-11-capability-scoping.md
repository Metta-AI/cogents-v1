# Capability Scoping Design

## Summary

Capabilities become first-class scoped objects. Calling `.scope()` on a capability returns a narrowed copy that enforces restrictions on every call. Scoped capabilities can be passed to helper functions, delegated via `spawn()`, or narrowed further — but never widened.

## Core Mechanism

Every capability subclass inherits scoping from the `Capability` base class. Scope is stored as a `_scope` dict on the instance. `.scope()` clones the instance with narrowed restrictions.

```python
class Capability:
    _scope: dict[str, Any]  # empty = unrestricted

    def scope(self, **kwargs) -> Self:
        """Return a new instance with narrowed scope."""
        new_scope = self._narrow(self._scope, kwargs)
        clone = copy(self)
        clone._scope = new_scope
        return clone

    def _narrow(self, existing: dict, requested: dict) -> dict:
        """Intersect existing scope with requested. Subclasses override."""
        return {**existing, **requested}

    def _check(self, op: str, **context) -> None:
        """Raise PermissionError if op is not allowed under current scope."""
        raise NotImplementedError
```

Each subclass overrides:
- `_narrow()` — intersection logic (longest prefix, intersection of op sets, etc.)
- `_check()` — called at the top of every public method to enforce scope

Scopes are composable: calling `.scope()` on a scoped instance can only narrow, never widen.

```python
config_files = dir.scope("/config", ops=["list", "read", "write"])
readonly_config = config_files.scope(ops=["list", "read"])  # narrower
```

## File-Related Capabilities

Three capabilities replace the single `files` capability:

| Capability | Scoped to | Operations |
|---|---|---|
| **file** | single key | `read`, `write`, `delete`, `get_metadata` |
| **file_version** | single key | `add`, `list`, `get`, `update` |
| **dir** | prefix | `list`, `read`, `write`, `create`, `delete` |

`dir` grants full file + version access to everything under its prefix.
`file` and `file_version` are for fine-grained single-key access.

```python
class FileCapability(Capability):
    ALL_OPS = {"read", "write", "delete", "get_metadata"}

    def scope(self, key: str | None = None, ops: list[str] | None = None) -> Self:
        return super().scope(key=key, ops=ops)

    def _narrow(self, existing, requested):
        key = requested.get("key") or existing.get("key")
        if existing.get("key") and requested.get("key") and existing["key"] != requested["key"]:
            raise ValueError("Cannot change scoped file key")
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        return {"key": key, "ops": sorted(old_ops & new_ops)}


class FileVersionCapability(Capability):
    ALL_OPS = {"add", "list", "get", "update"}

    def scope(self, key: str | None = None, ops: list[str] | None = None) -> Self:
        return super().scope(key=key, ops=ops)

    def _narrow(self, existing, requested):
        key = requested.get("key") or existing.get("key")
        if existing.get("key") and requested.get("key") and existing["key"] != requested["key"]:
            raise ValueError("Cannot change scoped file key")
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        return {"key": key, "ops": sorted(old_ops & new_ops)}


class DirCapability(Capability):
    ALL_OPS = {"list", "read", "write", "create", "delete"}

    def scope(self, prefix: str | None = None, ops: list[str] | None = None) -> Self:
        return super().scope(prefix=prefix, ops=ops)

    def _narrow(self, existing, requested):
        old_prefix = existing.get("prefix", "/")
        new_prefix = requested.get("prefix", old_prefix)
        if not new_prefix.startswith(old_prefix):
            raise ValueError(f"Cannot widen prefix from {old_prefix} to {new_prefix}")
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        return {"prefix": new_prefix, "ops": sorted(old_ops & new_ops)}
```

Usage:

```python
workspace = dir.scope("/workspace/")                        # full access to subtree
docs = dir.scope("/docs/", ops=["list", "read"])            # read-only subtree
config = file.scope("/config/system", ops=["read"])         # single file read
audit = file_version.scope("/logs/audit", ops=["add"])      # append versions only
```

## Other Capabilities

**EventsCapability**

```python
def scope(self, emit: list[str] | None = None, query: list[str] | None = None) -> Self:
# ["*"] = unrestricted. Patterns matched with fnmatch.
# _narrow: intersection of emit/query pattern lists
```

**DiscordCapability**

```python
def scope(self, channels: list[str] | None = None, ops: list[str] | None = None) -> Self:
# ALL_OPS = {"send", "react", "create_thread", "dm", "receive"}
# _narrow: intersection of channel lists + ops
```

**EmailCapability**

```python
def scope(self, to: list[str] | None = None, ops: list[str] | None = None) -> Self:
# ALL_OPS = {"send", "receive"}
# _narrow: intersection of recipient allowlist + ops
```

**ProcsCapability**

```python
def scope(self, ops: list[str] | None = None) -> Self:
# ALL_OPS = {"list", "get", "spawn"}
# _narrow: intersection of ops
```

**SecretsCapability**

```python
def scope(self, keys: list[str] | None = None) -> Self:
# _narrow: intersection of key patterns
```

**me, resources, scheduler** — no scoping.

## Named Grants

Each process-capability binding has a **name** — the alias the process sees in its namespace. This allows a process to have multiple grants of the same capability under different names with different scopes.

```
discord        → discord (unscoped)
email_me       → email.scope(to=["daveey@gmail.com"])
email_team     → email.scope(to=["team@company.com"])
workspace      → dir.scope("/workspace/")
audit_log      → file_version.scope("/logs/audit", ops=["add"])
```

The process code uses `email_me.send(...)` not `email.send(...)`.

`ProcessCapability` model:

```python
class ProcessCapability(BaseModel):
    id: UUID
    process: UUID       # FK -> Process
    capability: UUID    # FK -> Capability
    name: str           # namespace alias (e.g. "email_me")
    config: dict | None # scope config for this grant
```

DB unique constraint is `UNIQUE(process, name)` — not `(process, capability)` — so multiple grants of the same capability are allowed.

## Spawn Integration

`spawn()` accepts a dict mapping grant names to capability instances (scoped or unscoped). No strings.

```python
procs.spawn("worker", capabilities={
    "events": events,                                          # unscoped = full access
    "workspace": dir.scope("/workspace/", ops=["list", "read"]),  # scoped
    "audit_log": file_version.scope("/logs/audit", ops=["add"]),  # scoped
})
```

For each entry, `spawn()`:
1. Resolves the capability type from the instance
2. Reads `._scope` (empty dict if unscoped)
3. Creates `ProcessCapability(name=grant_name, config=scope_dict)` in the DB

At process boot, the sandbox reads `ProcessCapability.config` and calls `.scope(**config)` on the capability instance before injecting it into the process namespace under the grant name.

## Storage

`ProcessCapability.config` (JSONB) stores the scope dict. Format is capability-specific:

```json
{"key": "/config/system", "ops": ["read"]}
{"prefix": "/workspace/", "ops": ["list", "read"]}
{"emit": ["task:*"], "query": ["*"]}
```

Unscoped grants store `config = null`.

## Enforcement

Every public method on a capability starts with `self._check(op, **context)`:

```python
class FileCapability(Capability):
    def read(self, key: str) -> FileContent | FileError:
        self._check("read", key=key)
        # ... actual read logic
```

`_check()` raises `PermissionError` if the operation is not allowed. The sandbox catches this and returns an error to the process.
