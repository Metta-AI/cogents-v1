# DM Trace Profiling Design

## Problem
Discord DM handling is slow. The bridge starts responding, but the full round-trip from DM-sent to reply-received takes too long. There's no end-to-end visibility into where time is spent.

## Solution
Add a `trace_id` generated at the Discord bridge when a DM is received. Thread it through all stages of processing. Each stage stamps timing metadata. The bridge logs a full trace summary when the reply is sent.

## Design Decisions

- **Trace boundary:** Shallow — one inbound message = one trace. Child processes get separate traces with `parent_trace_id` for future stitching.
- **Storage:** Extend existing models (ChannelMessage, Delivery, Run) with `trace_id` fields. No new tables.
- **Coverage:** All 7 timing segments from Discord gateway to reply send.

## Timing Segments

| # | Span | Source |
|---|------|--------|
| 1 | Discord gateway → DB write | `trace_meta.db_written_at_ms - trace_meta.discord_created_at_ms` |
| 2 | DB write → scheduler match | `Delivery.created_at - trace_meta.db_written_at_ms` |
| 3 | Scheduler match → dispatch | `dispatched_at_ms - Delivery.created_at` |
| 4 | Dispatch → executor start | `executor_started_at_ms - dispatched_at_ms` |
| 5 | Executor done → SQS enqueue | `_meta.queued_at_ms - Run.completed_at` |
| 6 | SQS enqueue → SQS receive | `sqs_received_at_ms - queued_at_ms` |
| 7 | SQS receive → Discord send | `discord_sent_at_ms - sqs_received_at_ms` |

## Schema Changes

- `cogos_channel_message`: + `trace_id UUID`, `trace_meta JSONB`
- `cogos_delivery`: + `trace_id UUID`
- `cogos_run`: + `trace_id UUID`, `parent_trace_id UUID`

## Data Flow

1. Bridge receives DM → generates `trace_id`, stamps timing in `trace_meta`, writes to DB
2. Scheduler creates delivery → copies `trace_id` from message
3. Dispatcher invokes executor → adds `trace_id` + `dispatched_at_ms` to event payload
4. Executor starts → stamps `executor_started_at_ms`, sets `trace_id` on Run
5. Process sends reply via DiscordCapability → `trace_id` in SQS `_meta`
6. Bridge polls SQS → stamps `sqs_received_at_ms`
7. Bridge sends Discord message → logs `CogOS trace_complete` with full timing breakdown
