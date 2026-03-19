# Alert Monitoring Coglet — Design

## Overview

A daemon Python coglet that monitors system alerts in real-time and takes tiered action: auto-suppresses spam autonomously, escalates critical/high-impact events to the supervisor.

## Architecture

```
AlertsCapability._emit()
  ├── repo.create_alert()          (existing — DB write)
  └── repo.append_channel_message()  (new — publish to system:alerts)
        │
        ▼
  system:alerts channel
        │
        ▼
  alert-monitor coglet (daemon, python executor)
        │
        ├── query DB for recent 5min alert window
        ├── run 4 detection rules
        └── dispatch actions
              ├── suppress → emit monitor:* alert to DB
              └── escalate → send to supervisor:alerts channel
```

## Components

### 1. System Channels Registry — `src/cogos/lib/channels.py`

Centralizes all system channel definitions. Init calls `create_system_channels(repo)` at boot.

```python
SYSTEM_CHANNELS = [
    {"name": "system:alerts", "schema": {
        "id": "string",
        "severity": "string",
        "alert_type": "string",
        "source": "string",
        "message": "string",
        "metadata": "object",
        "timestamp": "string",
    }},
    {"name": "supervisor:alerts", "schema": {
        "rule": "string",
        "alert_type": "string",
        "source_process": "string",
        "summary": "string",
        "recent_alerts": "array",
        "recommended_action": "string",
    }},
    # ... existing system channels (system:tick:minute, etc.) moved here
]

def create_system_channels(repo):
    for ch_def in SYSTEM_CHANNELS:
        ch = Channel(
            name=ch_def["name"],
            owner_process=init_process_id,
            channel_type=ChannelType.NAMED,
            inline_schema={"fields": ch_def["schema"]} if ch_def.get("schema") else None,
        )
        repo.upsert_channel(ch)
```

### 2. AlertsCapability Patch — `src/cogos/capabilities/alerts.py`

Add channel publish after DB write in `_emit()`:

```python
def _emit(self, severity, alert_type, message, metadata):
    proc = self.repo.get_process(self.process_id)
    source = proc.name if proc else str(self.process_id)
    try:
        self.repo.create_alert(
            severity=severity, alert_type=alert_type,
            source=source, message=message, metadata=metadata,
        )
        # Publish to system:alerts channel for real-time monitoring
        alerts_ch = self.repo.get_channel_by_name("system:alerts")
        if alerts_ch:
            from cogos.db.models import ChannelMessage
            msg = ChannelMessage(
                channel=alerts_ch.id,
                sender_process=self.process_id,
                payload={
                    "severity": severity,
                    "alert_type": alert_type,
                    "source": source,
                    "message": message,
                    "metadata": metadata,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                },
            )
            self.repo.append_channel_message(msg)
        return AlertResult(id="ok", severity=severity, alert_type=alert_type)
    except Exception as e:
        return AlertError(error=str(e))
```

### 3. Alert Monitor Coglet

**`images/cogent-v1/apps/alert-monitor/cog.py`:**

```python
from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    executor="python",
    emoji="🚨",
    capabilities=["alerts", "channels", "procs"],
    handlers=["system:alerts"],
)
```

**`images/cogent-v1/apps/alert-monitor/main.py`:**

Entry point receives triggering alert payload, queries DB for context, runs rules, dispatches actions.

## Detection Rules

### Rule 1: Spam Detection

- Group alerts by `(source, alert_type)` in last 60s
- Threshold: >= 10 occurrences
- Auto-action: emit `monitor:spam_detected` alert with count and suppression key
- Self-dedup: skip if `monitor:suppressing` already exists for this key in the window

### Rule 2: Escalating Failure Rate

- Split 5-minute window into 5 x 60s buckets per source
- Trigger: last bucket count >= 2x average of prior buckets
- Action: escalate to `supervisor:alerts` with rate data

### Rule 3: Critical Signal

- Any alert with `severity="emergency"`
- Action: immediately escalate to `supervisor:alerts` with recent alert context from same source

### Rule 4: Unacknowledged Critical

- `severity="critical"` alerts where `acknowledged_at is None` and `created_at` > 5 minutes ago
- Action: escalate to `supervisor:alerts`
- Self-dedup: skip if `monitor:unack_escalation` referencing this alert ID already exists

## Action Dispatcher

```python
@dataclass
class Action:
    kind: str          # "suppress" | "escalate"
    alert_type: str    # e.g. "monitor:spam_detected"
    message: str
    metadata: dict
```

**Suppress actions:**
- Emit alert via `AlertsCapability` with `source="alert-monitor"`
- Metadata includes suppression key and count

**Escalate actions:**
- Send structured payload to `supervisor:alerts` channel:
  ```python
  {
      "rule": "critical_signal",
      "alert_type": "monitor:escalation",
      "source_process": "discord/handler",
      "summary": "3 emergency alerts from discord/handler in 60s",
      "recent_alerts": [...],
      "recommended_action": "investigate discord/handler",
  }
  ```
- Also emit `monitor:escalated` alert to DB for dashboard visibility

**Deduplication:**
- Before executing any action, check if identical action already taken in current window (same `alert_type` + metadata key)
- Prevents monitor from spamming its own actions during bursts

## Integration

- **Init**: calls `create_system_channels(repo)` at boot, spawns alert-monitor as detached daemon
- **AlertsCapability**: publishes to `system:alerts` channel after DB write; logs warning if channel missing (early boot edge case)
- **Supervisor**: subscribes to `supervisor:alerts` for escalation handling
- **Dashboard**: no changes — monitor outputs appear as regular alerts with `source="alert-monitor"`

## Testing

- **Unit tests**: feed synthetic alert lists to each rule function, assert correct actions
- **Integration test**: emit burst of alerts, verify monitor wakes and emits correct suppression/escalation alerts
- **Deduplication test**: verify monitor doesn't spam its own alerts during bursts
