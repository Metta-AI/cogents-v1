# Coglet Channels Design

## Summary

Standardize the channel set every coglet runs with, abstracting away whether the coglet is local or proxied. Five channels form the complete communication interface:

| Channel | Direction | Purpose |
|---------|-----------|---------|
| `io:stdin` | in | Task/event input — wakes idle coglets, appends to running conversations |
| `io:stdout` | out | Primary task output — optionally schema-validated |
| `io:stderr` | out | Diagnostics, errors, warnings, debug traces (Unix stderr semantics) |
| `cog:from` | in | Parent cog → coglet guidance, injected into conversation context |
| `cog:to` | out | Coglet → parent cog updates, sent explicitly |

## Design Decisions

### Channel naming: `io:*` vs `cog:*`
Two namespaces separate concerns:
- **`io:*`** — task I/O, wired by the cog to external systems. The parent cog does not monitor these.
- **`cog:*`** — the cog↔coglet relationship. The parent cog only communicates through these.

### `cog:from` injection
Messages from the parent cog are injected directly into the coglet's conversation context — no explicit read needed. This makes cog guidance feel natural and ensures the coglet acts on it without boilerplate.

### `cog:to` is explicit
The coglet sends updates to its parent by writing to `cog:to` explicitly. No automatic forwarding of lifecycle events — the coglet decides what's worth reporting.

### `io:stdin` wake-up
`io:stdin` and `cog:from` are independent wake-up sources. stdin is for task events; cog:from is for parent guidance.

### `io:stdout` schema validation
Optional. The spawning cog can declare an output schema; if present, stdout messages are validated against it. Schema violations are rejected and logged to stderr.

### `io:stderr` is not monitored by the cog
stderr is the coglet's own diagnostic stream. The parent cog does not read it — it only reads `cog:to`.

### Abstraction over transport
Today these map to spawn channels. The coglet doesn't need to know this. When coglets are proxied to remote clusters, the channel interface stays the same.

## Documentation

Standard include at `includes/coglet/channels.md` — injected into coglet system prompts via `@{cogos/includes/coglet/channels.md}`.

## Implementation Notes

- Map `io:stdin`/`io:stdout`/`io:stderr` to the existing `process:<name>:stdin/stdout/stderr` channels
- Map `cog:from`/`cog:to` to the existing spawn channels (`spawn:<parent>→<child>` / `spawn:<child>→<parent>`)
- Context engine needs to inject `cog:from` messages into coglet conversation context
- Schema validation on stdout uses existing `SchemaValidator` infrastructure
