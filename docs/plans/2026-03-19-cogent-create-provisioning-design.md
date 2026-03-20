# Cogent Create — External Service Provisioning

**Date:** 2026-03-19
**Status:** Design

## Goal

Make `polis cogent create` a one-command setup that provisions all external service accounts alongside the existing AWS infrastructure. After running it, a cogent has: a domain, database, CDK stack, Discord role, email address, Asana workspace access, and GitHub access.

## Current State

`polis cogents create <name>` already provisions:
1. Cloudflare DNS record
2. ACM certificate with DNS validation
3. DynamoDB status record
4. Database on shared RDS cluster + schema
5. Identity secret
6. Per-cogent CDK stack (IAM role, SQS, S3, EventBridge, ECS, ALB)

Missing: Discord role, email (SES), Asana guest invite, GitHub credentials.

## Design

### Command Flow Changes

The existing `cogents create` command is modified to:

1. **Prompt for name** — already exists as a CLI argument, keep as-is
2. **Show confirmation plan** — NEW: display all resources that will be created, ask for `y/n`
3. **Execute existing steps** — unchanged (DNS, cert, DB, schema, secrets, CDK)
4. **Execute new steps** — Discord role, SES identity, Asana invite, GitHub credentials
5. **Summary** — augmented to include new resources

### New Provisioning Steps

All new steps run after the CDK stack is deployed (step 7 in existing flow). Each stores its resource ID in secrets and DynamoDB for status reporting.

#### Step 8: Email (SES) — must be first, other services send invites to it

- Create SES email identity for `{name}@softmax-cogents.com`
- The existing SQS/S3 inbound pipeline handles receiving
- Store identity ARN in secret `cogent/{name}/ses_identity_arn`
- Store email address in DynamoDB status item

#### Step 9: Discord Role

- Read shared bot token from `polis/discord_bot_token` secret
- Read guild ID from `polis/discord_guild_id` secret
- Call Discord API `POST /guilds/{guild_id}/roles` to create role `cogent-{name}`
- Store role ID in secret `cogent/{name}/discord_role_id`
- Store role ID in DynamoDB status item

#### Step 10: Asana Guest Invite — depends on email being live

- Read Asana PAT from `polis/asana_pat` secret
- Read workspace GID from `polis/asana_workspace_gid` secret
- Call Asana API `POST /workspaces/{gid}/addUser` with `{name}@softmax-cogents.com`
- API returns a user GID immediately (user is in pending/invited state)
- Store the returned user GID in secret `cogent/{name}/asana_user_gid`
- Store user GID + status "invited" in DynamoDB status item
- Asana sends invite email to `{name}@softmax-cogents.com`
- SES inbound pipeline delivers it to the auto-accept Lambda
- Lambda parses the invite, extracts the accept link, hits it
- Lambda updates DynamoDB status from "invited" to "active"

#### Step 11: GitHub Credentials

- Read shared GitHub App credentials from `polis/github_app` secret
- Copy to `cogent/{name}/github` (the key the existing `GitHubCapability` already reads)
- Store "github-app (shared)" marker in DynamoDB status item

### Status Command Changes

`polis cogent status <name>` currently dumps raw JSON. Modify to show a formatted table like the top-level `polis status` command, adding rows for:

| Component | Source | Display |
|-----------|--------|---------|
| Discord Role | secret `cogent/{name}/discord_role_id` | role name + ID |
| Email | secret `cogent/{name}/ses_identity_arn` | address + verification status |
| Asana | secret `cogent/{name}/asana_user_gid` + DynamoDB | guest user GID + status (invited/active) |
| GitHub | secret `cogent/{name}/github` | auth type (app/token) |

Also add these rows to the per-cogent tables in the top-level `polis status` output.

### Shared Secrets (One-Time Setup)

These must exist before `polis cogent create` can provision external services:

| Secret Path | Contents |
|-------------|----------|
| `polis/discord_bot_token` | `{"bot_token": "..."}` |
| `polis/discord_guild_id` | `{"guild_id": "..."}` |
| `polis/asana_pat` | `{"access_token": "..."}` |
| `polis/asana_workspace_gid` | `{"workspace_gid": "..."}` |
| `polis/github_app` | `{"type": "github_app", "app_id": "...", "private_key": "...", "installation_id": "..."}` |

### Error Handling

Each new step is independent. If one fails:
- Log the error with `[yellow]` warning
- Continue with remaining steps
- The status command shows which resources are missing
- Admin can re-run or manually fix

### Destroy Command

`polis cogents destroy <name>` is augmented with cleanup for:
- Discord: delete the role via Bot API
- SES: delete the email identity
- Asana: remove guest from workspace
- GitHub: delete the cogent's github secret (shared app creds are not affected)

## Files Changed

| File | Change |
|------|--------|
| `src/polis/cli.py` | Add confirmation step, new provisioning steps 8-11, augment status + destroy |

No new files needed — all logic goes in the existing CLI module.
