# Run Analytics & Reliability Fixes

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix cost tracking, model_version persistence, stuck run reaping, file version race conditions, CLI output quality, and scheduler API discovery waste.

**Architecture:** Targeted fixes across executor, repository, dispatcher, file store, and CLI layers. Each fix is isolated and testable independently.

**Tech Stack:** Python 3.12+, PostgreSQL via RDS Data API, Pydantic models, Click CLI

---

### Task 1: Add cost calculation and model_version persistence to complete_run

**Files:**
- Modify: `src/cogos/db/repository.py:1047-1083` (add model_version param to complete_run)
- Modify: `src/cogos/db/local_repository.py:907-937` (same for local repo)
- Modify: `src/cogos/executor/handler.py:188-202,244-256` (calculate cost, pass model_version)
- Test: `tests/cogos/db/test_repository_runs.py`

**Step 1: Add model_version to complete_run in Repository**

In `repository.py`, add `model_version: str | None = None` parameter and persist it:

```python
def complete_run(
    self,
    run_id: UUID,
    *,
    status: RunStatus,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: Decimal = Decimal("0"),
    duration_ms: int | None = None,
    error: str | None = None,
    model_version: str | None = None,
    result: dict | None = None,
    snapshot: dict | None = None,
    scope_log: list[dict] | None = None,
) -> bool:
    response = self._execute(
        """UPDATE cogos_run SET
               status = :status, tokens_in = :tokens_in, tokens_out = :tokens_out,
               cost_usd = :cost_usd::numeric, duration_ms = :duration_ms,
               error = :error, model_version = COALESCE(:model_version, model_version),
               result = :result::jsonb,
               snapshot = COALESCE(:snapshot::jsonb, snapshot),
               scope_log = COALESCE(:scope_log::jsonb, scope_log),
               completed_at = now()
           WHERE id = :id""",
        [
            self._param("id", run_id),
            self._param("status", status.value),
            self._param("tokens_in", tokens_in),
            self._param("tokens_out", tokens_out),
            self._param("cost_usd", cost_usd),
            self._param("duration_ms", duration_ms),
            self._param("error", error),
            self._param("model_version", model_version),
            self._param("result", result),
            self._param("snapshot", snapshot),
            self._param("scope_log", scope_log),
        ],
    )
    return response.get("numberOfRecordsUpdated", 0) == 1
```

**Step 2: Add model_version to complete_run in LocalRepository**

Same parameter addition.

**Step 3: Add cost calculation helper and wire it in handler.py**

Add a `_estimate_cost` function and pass model_version + cost in both success and failure paths.

**Step 4: Run tests**

```bash
uv run pytest tests/cogos/db/test_repository_runs.py -v
```

---

### Task 2: Fix file version race condition (duplicate key)

**Files:**
- Modify: `src/cogos/db/repository.py:839-856` (insert_file_version with ON CONFLICT)

Change `insert_file_version` to use upsert:

```sql
INSERT INTO cogos_file_version (id, file_id, version, read_only, content, source, is_active)
VALUES (:id, :file_id, :version, :read_only, :content, :source, :is_active)
ON CONFLICT (file_id, version) DO UPDATE SET
    content = EXCLUDED.content,
    source = EXCLUDED.source,
    is_active = EXCLUDED.is_active
```

---

### Task 3: Add stuck run reaper to dispatcher

**Files:**
- Modify: `src/cogtainer/lambdas/dispatcher/handler.py:97-118` (add run reaping)
- Modify: `src/cogos/db/repository.py` (add timeout_stale_runs method)

Add a method to mark runs as TIMEOUT if they've been RUNNING longer than 15 minutes (Lambda max is 15min).

---

### Task 4: Improve CLI run list output

**Files:**
- Modify: `src/cogos/cli/__main__.py:792-811` (enrich run list with process names, cost, model)

---

### Task 5: Improve scheduler system prompt with API surface

**Files:**
- Modify: `src/cogos/executor/handler.py:930-932` (inject capability method signatures into __capabilities__)

Instead of just listing capability names, include method signatures so the model doesn't waste turns on API discovery.
