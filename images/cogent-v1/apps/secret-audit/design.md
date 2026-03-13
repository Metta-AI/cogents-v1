# Secret Audit App

`secret-audit` is a reference app for capability-scoped repository auditing.

It demonstrates a useful split:

- A root daemon can orchestrate work, manage job files, and narrow grants.
- A `scout` child can search files under a target prefix but cannot read from the
  secret store.
- A `verifier` child can read selected evidence and fetch scoped secrets, but it
  cannot traverse the full workspace.

That makes it a good example of "find a secret vs. prove whether it is really a
live secret" without giving every process the same authority.

## Flow

1. Send a request to `secret-audit:requests`.
2. The daemon writes a job record under `apps/secret-audit/jobs/`.
3. It spawns a `scout` child with read-only access to the requested prefix.
4. The scout writes evidence under `apps/secret-audit/evidence/` and emits a
   structured event on `secret-audit:events`.
5. The daemon spawns a `verifier` child with:
   - read access to the evidence artifact
   - scoped `secrets` access
   - no broad workspace traversal
6. The verifier writes a verification artifact and emits a second event.
7. The daemon writes a final report and publishes a summary on
   `secret-audit:findings`.

## Example request

```bash
cogent local cogos channel send secret-audit:requests --payload '{
  "prefix": "workspace/",
  "report_key": "apps/secret-audit/reports/manual-scan.md",
  "reason": "pre-merge secret audit",
  "secret_keys": ["polis/shared/jwt-signing-key", "cogent/local/discord"]
}'
```

The request schema is strict. If you want defaults from `config.json`, pass an
empty string for `prefix` or `report_key`, and an empty list for `secret_keys`.

## Why this app is reusable

- The target area, ignore prefixes, default secret keys, and output prefixes all
  live in `config.json`.
- Detection guidance lives in `heuristics.md`.
- Report shape lives in `report-format.md`.
- The orchestration pattern is generic: request channel, staged child workers,
  events channel, final report.
