# Email Capability

Cloudflare Email Routing for inbound, AWS SES for outbound. Replaces the
Gmail service account approach with a free, API-driven setup that makes it
trivial to provision new cogent email addresses.

## Architecture

```
Inbound:
  sender -> MX (Cloudflare) -> Email Worker -> HTTPS POST -> Ingest Lambda
         -> INSERT INTO events (status='proposed') -> Dispatcher -> Orchestrator

Outbound:
  Process calls email/send capability -> SES SendEmail API -> recipient
```

### Why This Over Gmail

- **Free.** Cloudflare Email Routing is free. SES is $0.10/1000 emails.
- **No Google Workspace.** Eliminates the service account + domain-wide
  delegation setup.
- **Programmatic provisioning.** Cloudflare API creates routing rules per
  cogent. No manual admin console steps.
- **Simpler credentials.** SES uses IAM roles (already in the execution
  environment). No service account JSON keys in Secrets Manager.

## Components

### 1. Cloudflare Email Worker

A single Worker deployed once for the whole domain. Routes emails to the
correct cogent's ingest endpoint based on the recipient address.

```
softmax-cogents.com MX -> Cloudflare Email Routing -> catch-all -> Worker
```

The Worker:
1. Parses the raw email (headers, text body, sender, recipient).
2. Extracts the cogent name from the recipient local part
   (e.g., `ovo@softmax-cogents.com` -> cogent `ovo`).
3. POSTs a JSON payload to the cogent's ingest endpoint.

```javascript
export default {
  async email(message, env, ctx) {
    const to = message.to;
    const from = message.from;
    const localPart = to.split("@")[0];

    // Read raw email
    const rawEmail = await new Response(message.raw).text();

    // Parse headers
    const subject = message.headers.get("subject") || "(no subject)";
    const messageId = message.headers.get("message-id") || "";
    const date = message.headers.get("date") || "";

    // Extract text body from raw MIME (simple extraction)
    const body = extractTextBody(rawEmail);

    // Look up cogent ingest URL from KV
    const ingestUrl = await env.COGENT_ROUTES.get(localPart);
    if (!ingestUrl) {
      // Unknown recipient — reject or forward to a catch-all
      message.setReject("Unknown recipient");
      return;
    }

    const payload = {
      event_type: "email:received",
      source: "cloudflare-email-worker",
      payload: {
        from: from,
        to: to,
        subject: subject,
        body: body,
        message_id: messageId,
        date: date,
        cogent: localPart,
      },
    };

    // POST to cogent ingest endpoint with shared secret
    const resp = await fetch(ingestUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${env.INGEST_SECRET}`,
      },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      // Retry will happen via CF Email Routing retry policy
      throw new Error(`Ingest failed: ${resp.status}`);
    }
  },
};
```

**Routing config** is stored in Cloudflare Workers KV. One KV entry per
cogent maps the local part to the ingest URL:

```
ovo  ->  https://ovo.softmax-cogents.com/api/ingest/email
alpha -> https://alpha.softmax-cogents.com/api/ingest/email
```

### 2. Ingest Endpoint

A route on the existing dashboard FastAPI app. Validates the bearer token,
inserts into the `events` table with `status='proposed'`.

```
POST /api/ingest/email
Authorization: Bearer <INGEST_SECRET>
Content-Type: application/json

{
  "event_type": "email:received",
  "source": "cloudflare-email-worker",
  "payload": { ... }
}
```

Handler:

```python
@router.post("/ingest/email")
async def ingest_email(request: Request, body: dict):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not _verify_ingest_token(token):
        raise HTTPException(status_code=401)

    repo = get_repo()
    event = Event(
        event_type=body["event_type"],
        source=body["source"],
        payload=body["payload"],
    )
    event_id = repo.append_event(event, status="proposed")
    return {"event_id": event_id}
```

This flows into the existing pipeline: Dispatcher Lambda picks up proposed
events, publishes to EventBridge, Orchestrator matches triggers.

### 3. SES Sender

Replaces `GmailSender`. Uses boto3 SES client with IAM auth (no extra
credentials needed in Lambda/ECS since the execution role has SES
permissions).

```python
class SesSender:
    def __init__(self, from_address: str, region: str = "us-east-1"):
        self._from = from_address
        self._client = boto3.client("ses", region_name=region)

    def send(self, to: str, subject: str, body: str,
             reply_to: str | None = None) -> dict:
        kwargs = {
            "Source": self._from,
            "Destination": {"ToAddresses": [to]},
            "Message": {
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body}},
            },
        }
        if reply_to:
            kwargs["ReplyToAddresses"] = [reply_to]
        return self._client.send_email(**kwargs)
```

### 4. Email Capability

Registered as a CogOS capability. Processes interact with email through
the `email` proxy object.

```python
# In sandbox:
email.check(query="is:unread", limit=10)
email.send(to="user@example.com", subject="Update", body="...")
email.search(query="from:alice subject:review")
```

Capability definitions:

```
email/send
  handler: cogos.lib.email.send
  input:   { to: str, subject: str, body: str, reply_to?: str }
  output:  { message_id: str, to: str, subject: str }

email/check
  handler: cogos.lib.email.check
  input:   { query?: str, limit?: int }
  output:  list[{ from, to, subject, body, date, message_id }]

email/search
  handler: cogos.lib.email.search
  input:   { query: str, limit?: int }
  output:  list[{ from, to, subject, body, date, message_id }]
```

`email/check` and `email/search` query the `events` table for
`email:received` events. No external API call needed — the emails are
already in the database.

```python
def check(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    limit = args.get("limit", 10)
    events = repo.get_events(event_type="email:received", limit=limit)
    return CapabilityResult(content=[
        {
            "from": e.payload.get("from"),
            "to": e.payload.get("to"),
            "subject": e.payload.get("subject"),
            "body": e.payload.get("body"),
            "date": e.payload.get("date"),
            "message_id": e.payload.get("message_id"),
        }
        for e in events
    ])
```

### 5. Provisioning CLI

Extends the existing `channels create` CLI to provision a new cogent email
address. Steps:

1. Create Cloudflare Email Routing rule via API (match recipient, route to
   Worker).
2. Add KV entry mapping local part to cogent ingest URL.
3. Verify the cogent's domain identity in SES (one-time per domain).
4. Store the `from_address` in Secrets Manager or the `channels` DB table.

```
cogent channels create email ovo
  -> Creates CF routing rule for ovo@softmax-cogents.com
  -> Adds KV entry: ovo -> https://ovo.softmax-cogents.com/api/ingest/email
  -> Registers ovo@softmax-cogents.com as verified sender in SES
  -> Stores config in channels table
```

## Cloudflare Setup (One-Time)

1. Add `softmax-cogents.com` to Cloudflare (if not already).
2. Set MX records to Cloudflare Email Routing.
3. Enable Email Routing in the Cloudflare dashboard.
4. Create a Workers KV namespace (`COGENT_ROUTES`).
5. Deploy the Email Worker with a catch-all route.
6. Store `INGEST_SECRET` as a Worker secret.
7. Verify `softmax-cogents.com` domain in SES.

## SES Setup (One-Time Per Domain)

1. Verify domain identity in SES (`softmax-cogents.com`).
2. Add DKIM records (Cloudflare DNS).
3. Request production access (move out of sandbox).
4. Grant `ses:SendEmail` to Lambda/ECS execution roles (CDK).

## CDK Changes

Add to `BrainStack`:

```python
# SES send permission for executor roles
compute.executor_role.add_to_policy(
    iam.PolicyStatement(
        actions=["ses:SendEmail", "ses:SendRawEmail"],
        resources=[f"arn:aws:ses:{region}:{account}:identity/softmax-cogents.com"],
    )
)
```

No new Lambda needed — the ingest endpoint runs on the existing dashboard
Fargate service.

## Security

- **Ingest auth.** Bearer token shared between CF Worker and dashboard.
  Stored as CF Worker secret and in AWS Secrets Manager.
- **SES sending.** Scoped IAM policy — can only send from
  `*@softmax-cogents.com`.
- **No open relay.** The ingest endpoint only accepts
  `email:received` events and validates the token.

## Migration

1. Deploy CF Worker and SES domain verification.
2. Add email capability to CogOS.
3. Update MX records to point to Cloudflare.
4. Test inbound + outbound.
5. Remove Gmail service account credentials and tools.
6. Remove `src/channels/gmail/` and `eggs/ovo/tools/channels/gmail/`.

## Package Structure

```
cogos/lib/email/
    __init__.py         re-exports
    design.md           this document
    sender.py           SesSender (SES outbound)
    capability.py       email/send, email/check, email/search handlers
    ingest.py           FastAPI router for ingest endpoint
    provision.py        CLI provisioning (CF API + SES + KV)
    worker.js           Cloudflare Email Worker source

cogos/capabilities/__init__.py
    + email capability definitions in BUILTIN_CAPABILITIES
```
