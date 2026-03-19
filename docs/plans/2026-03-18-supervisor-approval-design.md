# Supervisor Manager Approval

Supervisor can escalate to a human manager when uncertain. Posts a proposal on Discord (DM + approvals channel), manager reacts 👍/👎, supervisor resumes or abandons.

## Manager Identity

Stored in secrets under `identity/manager/`:
- `identity/manager/name` — human-readable name
- `identity/manager/discord` — Discord user ID (for DMs)
- `identity/manager/email` — email (for future channels)
- `identity/manager/approvals_channel` — dedicated approvals channel ID

On startup, supervisor resolves the manager's DM channel ID via Discord API and caches it.

## When to Propose

Three conditions trigger a proposal instead of direct action:

1. **Ambiguous intent** — request has two or more plausible interpretations and supervisor isn't confident in its chosen one.
2. **Borderline security** — security screen doesn't flag as a clear threat, but touches sensitive areas. New `PROPOSE` outcome alongside `ALLOW` and `REFUSE`.
3. **Policy gap** — no existing program or trigger covers this type of request; novel situation.

Decision point sits after security screening, before delegation. Third branch alongside "respond directly" and "delegate to worker."

## Proposal Flow

1. Supervisor generates a proposal:
   - `proposal_id` (UUID)
   - `action` — what it plans to do
   - `reasoning` — why it's uncertain
   - `original_context` — request metadata (discord channel, message, author)

2. Stashes proposal as a channel message on `supervisor:proposals`.

3. Posts to Discord (both manager DM and approvals channel):
   ```
   📋 Proposal [short-id]

   Action: Create an Asana project called "Q2 Planning" for @dave

   Reasoning: User asked to "set up the Q2 stuff" — this is
   ambiguous. Could mean Asana project, GitHub repo, or calendar
   events. Going with Asana project based on recent context.

   👍 to approve · 👎 to reject
   ```

4. Reacts 📋 on the original user message (if any) to signal pending approval.

5. Returns control — supervisor doesn't block, moves on to other work.

## Reaction Handling & Resume

1. Discord bridge handles `MESSAGE_REACTION_ADD` gateway events, filters to reactions on cogent's own messages, relays as `discord:reaction` event with `message_id`, `reactor_id`, `emoji`, `channel_id`.

2. Supervisor trigger on `discord:reaction*` pattern.

3. On wakeup, supervisor:
   - Looks up proposal from `supervisor:proposals` by message ID
   - Validates `reactor_id` matches `identity/manager/discord` (ignores others)
   - 👍: executes stashed action with original context
   - 👎: posts "Proposal rejected" on DM + approvals channel, reacts ❌ on original message

4. Posts outcome (success/failure/rejected) as reply to proposal message.

## No Timeout

Proposals stay open indefinitely. Supervisor is event-driven — it parks the proposal and resumes on reaction event. No polling or timeout logic.

## Changes Required

**Discord bridge** (`src/cogos/io/discord/bridge.py`):
- Handle `MESSAGE_REACTION_ADD` gateway events
- Filter to reactions on messages sent by the cogent
- Relay as `discord:reaction` event

**Supervisor prompt** (`images/cogent-v1/cogos/supervisor/`):
- `main.md` — third branch: propose
- `security.md` — add `PROPOSE` outcome
- New `propose.md` — proposal generation, stashing, Discord posting

**Supervisor cog** (`images/cogent-v1/cogos/supervisor/cog.py`):
- `supervisor:proposals` channel subscription
- Trigger for `discord:reaction*`

**Secrets**:
- `identity/manager/name`
- `identity/manager/discord`
- `identity/manager/email`
- `identity/manager/approvals_channel`

No new infrastructure. Uses existing channels, triggers, Discord bridge, and secrets.
