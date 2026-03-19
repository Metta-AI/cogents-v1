# Alert Monitoring Coglet — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a daemon Python coglet that monitors system alerts in real-time, auto-suppresses spam, and escalates critical events to the supervisor.

**Architecture:** Alerts flow through a `system:alerts` channel (added to `AlertsCapability._emit()`). A Python-executor daemon coglet subscribes, wakes per alert, queries recent alerts from DB (stateless), runs 4 detection rules, and dispatches tiered actions (auto-suppress or escalate). System channels are centralized in a new `src/cogos/lib/channels.py`.

**Tech Stack:** Python, Pydantic, LocalRepository, existing CogOS capabilities (alerts, channels, procs)

**Design doc:** `docs/plans/2026-03-18-alert-monitor-design.md`

---

### Task 1: System Channels Registry

Create `src/cogos/lib/channels.py` — a centralized list of all system channels, with a function to create them at boot.

**Files:**
- Create: `src/cogos/lib/__init__.py`
- Create: `src/cogos/lib/channels.py`
- Create: `tests/cogos/lib/test_channels.py`

**Step 1: Write the failing test**

```python
# tests/cogos/lib/test_channels.py
"""Tests for system channels registry."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Process, ProcessStatus
from cogos.lib.channels import SYSTEM_CHANNELS, ensure_system_channels


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def test_ensure_system_channels_creates_all(tmp_path):
    """All channels in SYSTEM_CHANNELS are created."""
    repo = _repo(tmp_path)
    # Need an init process as owner
    init = Process(name="init", status=ProcessStatus.RUNNING, runner="local")
    init_id = repo.upsert_process(init)

    ensure_system_channels(repo, init_id)

    for ch_def in SYSTEM_CHANNELS:
        ch = repo.get_channel_by_name(ch_def["name"])
        assert ch is not None, f"Channel {ch_def['name']} not created"


def test_ensure_system_channels_idempotent(tmp_path):
    """Calling twice doesn't error or duplicate."""
    repo = _repo(tmp_path)
    init = Process(name="init", status=ProcessStatus.RUNNING, runner="local")
    init_id = repo.upsert_process(init)

    ensure_system_channels(repo, init_id)
    ensure_system_channels(repo, init_id)

    for ch_def in SYSTEM_CHANNELS:
        ch = repo.get_channel_by_name(ch_def["name"])
        assert ch is not None


def test_system_alerts_channel_has_schema(tmp_path):
    """system:alerts channel has an inline schema."""
    repo = _repo(tmp_path)
    init = Process(name="init", status=ProcessStatus.RUNNING, runner="local")
    init_id = repo.upsert_process(init)

    ensure_system_channels(repo, init_id)

    ch = repo.get_channel_by_name("system:alerts")
    assert ch.inline_schema is not None
    assert "fields" in ch.inline_schema
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/lib/test_channels.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cogos.lib'`

**Step 3: Write the implementation**

```python
# src/cogos/lib/__init__.py
```

```python
# src/cogos/lib/channels.py
"""System channels registry — centralized definitions for all CogOS system channels."""

from __future__ import annotations

from uuid import UUID

from cogos.db.models import Channel, ChannelType


SYSTEM_CHANNELS: list[dict] = [
    # Alerts pipeline
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
    # Scheduling
    {"name": "system:tick:minute"},
    {"name": "system:tick:hour"},
    # Supervisor
    {"name": "supervisor:help"},
    # Discord IO
    {"name": "io:discord:dm"},
    {"name": "io:discord:mention"},
    {"name": "io:discord:message"},
    {"name": "io:discord:api:request"},
    {"name": "io:discord:api:response"},
    {"name": "discord-cog:review"},
    # Web
    {"name": "io:web:request"},
    # GitHub
    {"name": "github:discover"},
    # Diagnostics
    {"name": "system:diagnostics"},
]


def ensure_system_channels(repo, owner_process_id: UUID) -> None:
    """Create all system channels if they don't exist."""
    for ch_def in SYSTEM_CHANNELS:
        inline_schema = None
        if ch_def.get("schema"):
            inline_schema = {"fields": ch_def["schema"]}

        ch = Channel(
            name=ch_def["name"],
            owner_process=owner_process_id,
            channel_type=ChannelType.NAMED,
            inline_schema=inline_schema,
        )
        repo.upsert_channel(ch)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogos/lib/test_channels.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add src/cogos/lib/__init__.py src/cogos/lib/channels.py tests/cogos/lib/test_channels.py
git commit -m "feat(lib): add centralized system channels registry"
```

---

### Task 2: Migrate init.py to use system channels registry

Replace the inline channel creation loop in `images/cogent-v1/cogos/init.py` with a call referencing the same channel list.

**Files:**
- Modify: `images/cogent-v1/cogos/init.py:99-110`

**Step 1: Update init.py**

Replace the hardcoded channel creation loop (lines 99-110):

```python
# ── Channels (created at boot so handlers can subscribe) ──────
for ch_name in [
    "io:discord:dm", "io:discord:mention", "io:discord:message",
    "io:discord:api:request", "io:discord:api:response",
    "discord-cog:review",
    "system:tick:minute", "system:tick:hour",
    "supervisor:help",
    "io:web:request",
    "github:discover",
    "system:diagnostics",
]:
    channels.create(ch_name)
```

With a reference to the centralized list. Since init.py runs inside the sandbox (no imports), we can't call `ensure_system_channels()` directly. Instead, init.py still uses `channels.create()` but iterates over a list that the image build process writes to the FileStore from `SYSTEM_CHANNELS`.

**However**, the simpler approach: keep init.py creating channels via its `channels` capability, but use the same channel names. The registry in `src/cogos/lib/channels.py` is the source of truth, and init.py's list is derived from it at image build time.

**Simplest path**: Leave init.py's channel creation as-is for now but add `system:alerts` and `supervisor:alerts` to its list. The registry serves as documentation and is used by tests/infra code. Migrating init.py to use the registry is a separate concern (requires changes to the image build pipeline).

Replace lines 99-110 in init.py:

```python
# ── Channels (created at boot so handlers can subscribe) ──────
for ch_name in [
    "io:discord:dm", "io:discord:mention", "io:discord:message",
    "io:discord:api:request", "io:discord:api:response",
    "discord-cog:review",
    "system:tick:minute", "system:tick:hour",
    "supervisor:help",
    "io:web:request",
    "github:discover",
    "system:diagnostics",
    "system:alerts",
    "supervisor:alerts",
]:
    channels.create(ch_name)
```

**Step 2: Verify existing tests still pass**

Run: `python -m pytest tests/cogos/ -k "init or channel" --timeout=30 -v`
Expected: All existing tests pass

**Step 3: Commit**

```bash
git add images/cogent-v1/cogos/init.py
git commit -m "feat(init): add system:alerts and supervisor:alerts channels at boot"
```

---

### Task 3: Patch AlertsCapability to publish to system:alerts channel

After writing to DB, also publish the alert as a channel message.

**Files:**
- Modify: `src/cogos/capabilities/alerts.py`
- Create: `tests/cogos/capabilities/test_alerts_channel.py`

**Step 1: Write the failing test**

```python
# tests/cogos/capabilities/test_alerts_channel.py
"""Tests for alerts -> channel pipeline."""

from datetime import datetime, timezone
from uuid import uuid4

from cogos.capabilities.alerts import AlertsCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelType, Process, ProcessStatus


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    proc = Process(name="test-proc", status=ProcessStatus.RUNNING, runner="local")
    proc_id = repo.upsert_process(proc)

    # Create system:alerts channel
    ch = Channel(
        name="system:alerts",
        owner_process=proc_id,
        channel_type=ChannelType.NAMED,
    )
    repo.upsert_channel(ch)

    cap = AlertsCapability(repo, proc_id)
    return repo, proc_id, cap


def test_warning_publishes_to_channel(tmp_path):
    """alerts.warning() writes to DB AND sends to system:alerts channel."""
    repo, proc_id, cap = _setup(tmp_path)

    result = cap.warning("test:noisy", "something happened")

    assert result.severity == "warning"

    # Check channel message was sent
    ch = repo.get_channel_by_name("system:alerts")
    msgs = repo.list_channel_messages(ch.id, limit=10)
    assert len(msgs) == 1
    assert msgs[0].payload["alert_type"] == "test:noisy"
    assert msgs[0].payload["severity"] == "warning"
    assert msgs[0].payload["source"] == "test-proc"


def test_error_publishes_to_channel(tmp_path):
    """alerts.error() writes to DB AND sends to system:alerts channel."""
    repo, proc_id, cap = _setup(tmp_path)

    result = cap.error("executor:crash", "OOM kill")

    assert result.severity == "critical"

    ch = repo.get_channel_by_name("system:alerts")
    msgs = repo.list_channel_messages(ch.id, limit=10)
    assert len(msgs) == 1
    assert msgs[0].payload["alert_type"] == "executor:crash"
    assert msgs[0].payload["severity"] == "critical"


def test_alert_without_channel_still_works(tmp_path):
    """If system:alerts channel doesn't exist, alert still goes to DB."""
    repo = LocalRepository(str(tmp_path))
    proc = Process(name="test-proc", status=ProcessStatus.RUNNING, runner="local")
    proc_id = repo.upsert_process(proc)

    # No system:alerts channel created
    cap = AlertsCapability(repo, proc_id)
    result = cap.warning("test:thing", "no channel")

    assert result.severity == "warning"
    alerts = repo.list_alerts()
    assert len(alerts) == 1
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/capabilities/test_alerts_channel.py -v`
Expected: FAIL — `test_warning_publishes_to_channel` fails because no channel message is sent

**Step 3: Write the implementation**

Update `src/cogos/capabilities/alerts.py`:

```python
"""Alerts capability — emit warnings and errors to the algedonic channel."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from pydantic import BaseModel

from cogos.capabilities.base import Capability

logger = logging.getLogger(__name__)


class AlertResult(BaseModel):
    id: str
    severity: str
    alert_type: str


class AlertError(BaseModel):
    error: str


class AlertsCapability(Capability):
    """Emit system alerts (warnings, errors) visible in the dashboard.

    Usage:
        alerts.warning("scheduler:stuck", "Process X was stuck, recovered")
        alerts.error("executor:crash", "Run failed with OOM")
    """

    def warning(self, alert_type: str, message: str, **metadata) -> AlertResult | AlertError:
        """Emit a warning alert."""
        return self._emit("warning", alert_type, message, metadata)

    def error(self, alert_type: str, message: str, **metadata) -> AlertResult | AlertError:
        """Emit a critical-severity alert."""
        return self._emit("critical", alert_type, message, metadata)

    def _emit(self, severity: str, alert_type: str, message: str, metadata: dict) -> AlertResult | AlertError:
        proc = self.repo.get_process(self.process_id)
        source = proc.name if proc else str(self.process_id)
        try:
            self.repo.create_alert(
                severity=severity,
                alert_type=alert_type,
                source=source,
                message=message,
                metadata=metadata,
            )
            # Publish to system:alerts channel for real-time monitoring
            self._publish_to_channel(severity, alert_type, source, message, metadata)
            return AlertResult(id="ok", severity=severity, alert_type=alert_type)
        except Exception as e:
            return AlertError(error=str(e))

    def _publish_to_channel(
        self, severity: str, alert_type: str, source: str, message: str, metadata: dict,
    ) -> None:
        """Best-effort publish to system:alerts channel."""
        try:
            alerts_ch = self.repo.get_channel_by_name("system:alerts")
            if alerts_ch is None:
                return
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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            self.repo.append_channel_message(msg)
        except Exception:
            logger.warning("Failed to publish alert to system:alerts channel", exc_info=True)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogos/capabilities/test_alerts_channel.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add src/cogos/capabilities/alerts.py tests/cogos/capabilities/test_alerts_channel.py
git commit -m "feat(alerts): publish alerts to system:alerts channel for real-time monitoring"
```

---

### Task 4: Detection Rules Engine

Pure functions that take a list of alerts and return a list of actions.

**Files:**
- Create: `images/cogent-v1/apps/alert-monitor/rules.py`
- Create: `tests/cogos/test_alert_monitor_rules.py`

**Step 1: Write the failing tests**

```python
# tests/cogos/test_alert_monitor_rules.py
"""Tests for alert monitor detection rules."""

from datetime import datetime, timezone, timedelta
from uuid import uuid4

from cogos.db.models.alert import Alert, AlertSeverity


# We'll import the rules module from the image path — add it to sys.path in conftest
# or just inline the rule functions for testing. Since this is a sandbox script,
# we test the rule logic as standalone functions.

# For testability, the rules are also available as a module:
# We'll create a thin wrapper in src/cogos/lib/alert_rules.py that the tests import,
# and the coglet's main.py also uses.


def _alert(
    alert_type="test:error",
    source="test-proc",
    severity=AlertSeverity.WARNING,
    message="test",
    created_at=None,
    acknowledged_at=None,
    metadata=None,
):
    return Alert(
        severity=severity,
        alert_type=alert_type,
        source=source,
        message=message,
        created_at=created_at or datetime.now(timezone.utc),
        acknowledged_at=acknowledged_at,
        metadata=metadata or {},
    )


def _now():
    return datetime.now(timezone.utc)


# ---- Rule 1: Spam Detection ----

def test_spam_detection_triggers_at_threshold():
    from cogos.lib.alert_rules import detect_spam
    now = _now()
    alerts = [_alert(created_at=now - timedelta(seconds=i)) for i in range(10)]
    actions = detect_spam(alerts, window_seconds=60, threshold=10)
    assert len(actions) == 1
    assert actions[0].kind == "suppress"
    assert actions[0].alert_type == "monitor:spam_detected"


def test_spam_detection_no_trigger_below_threshold():
    from cogos.lib.alert_rules import detect_spam
    now = _now()
    alerts = [_alert(created_at=now - timedelta(seconds=i)) for i in range(5)]
    actions = detect_spam(alerts, window_seconds=60, threshold=10)
    assert len(actions) == 0


def test_spam_detection_groups_by_source_and_type():
    from cogos.lib.alert_rules import detect_spam
    now = _now()
    # 10 from source A, 5 from source B — only A triggers
    alerts_a = [_alert(source="a", alert_type="err", created_at=now - timedelta(seconds=i)) for i in range(10)]
    alerts_b = [_alert(source="b", alert_type="err", created_at=now - timedelta(seconds=i)) for i in range(5)]
    actions = detect_spam(alerts_a + alerts_b, window_seconds=60, threshold=10)
    assert len(actions) == 1
    assert actions[0].metadata["source"] == "a"


def test_spam_detection_skips_own_alerts():
    from cogos.lib.alert_rules import detect_spam
    now = _now()
    alerts = [_alert(source="alert-monitor", alert_type="monitor:spam_detected", created_at=now - timedelta(seconds=i)) for i in range(20)]
    actions = detect_spam(alerts, window_seconds=60, threshold=10)
    assert len(actions) == 0


# ---- Rule 2: Escalating Failure Rate ----

def test_escalating_rate_triggers():
    from cogos.lib.alert_rules import detect_escalating_rate
    now = _now()
    # 2 alerts in each of first 4 minutes, 10 in last minute
    alerts = []
    for minute in range(4):
        for _ in range(2):
            alerts.append(_alert(created_at=now - timedelta(minutes=4 - minute, seconds=30)))
    for i in range(10):
        alerts.append(_alert(created_at=now - timedelta(seconds=i)))
    actions = detect_escalating_rate(alerts, window_seconds=300, buckets=5)
    assert len(actions) == 1
    assert actions[0].kind == "escalate"


def test_escalating_rate_no_trigger_steady():
    from cogos.lib.alert_rules import detect_escalating_rate
    now = _now()
    # 3 alerts per minute, steady
    alerts = []
    for minute in range(5):
        for j in range(3):
            alerts.append(_alert(created_at=now - timedelta(minutes=4 - minute, seconds=j * 10)))
    actions = detect_escalating_rate(alerts, window_seconds=300, buckets=5)
    assert len(actions) == 0


# ---- Rule 3: Critical Signal ----

def test_critical_signal_emergency():
    from cogos.lib.alert_rules import detect_critical_signal
    now = _now()
    alerts = [_alert(severity=AlertSeverity.EMERGENCY, created_at=now)]
    actions = detect_critical_signal(alerts)
    assert len(actions) == 1
    assert actions[0].kind == "escalate"
    assert actions[0].alert_type == "monitor:critical_signal"


def test_critical_signal_ignores_warning():
    from cogos.lib.alert_rules import detect_critical_signal
    now = _now()
    alerts = [_alert(severity=AlertSeverity.WARNING, created_at=now)]
    actions = detect_critical_signal(alerts)
    assert len(actions) == 0


# ---- Rule 4: Unacknowledged Critical ----

def test_unacked_critical_triggers():
    from cogos.lib.alert_rules import detect_unacked_critical
    old = _now() - timedelta(minutes=6)
    alerts = [_alert(severity=AlertSeverity.CRITICAL, created_at=old, acknowledged_at=None)]
    actions = detect_unacked_critical(alerts, stale_minutes=5)
    assert len(actions) == 1
    assert actions[0].kind == "escalate"
    assert actions[0].alert_type == "monitor:unack_escalation"


def test_unacked_critical_skips_acknowledged():
    from cogos.lib.alert_rules import detect_unacked_critical
    old = _now() - timedelta(minutes=6)
    alerts = [_alert(severity=AlertSeverity.CRITICAL, created_at=old, acknowledged_at=_now())]
    actions = detect_unacked_critical(alerts, stale_minutes=5)
    assert len(actions) == 0


def test_unacked_critical_skips_recent():
    from cogos.lib.alert_rules import detect_unacked_critical
    recent = _now() - timedelta(minutes=2)
    alerts = [_alert(severity=AlertSeverity.CRITICAL, created_at=recent, acknowledged_at=None)]
    actions = detect_unacked_critical(alerts, stale_minutes=5)
    assert len(actions) == 0
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/cogos/test_alert_monitor_rules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cogos.lib.alert_rules'`

**Step 3: Write the implementation**

```python
# src/cogos/lib/alert_rules.py
"""Alert monitoring detection rules.

Each rule is a pure function: takes a list of Alert objects, returns a list of Action objects.
Stateless — all context comes from the alert list passed in.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from cogos.db.models.alert import Alert, AlertSeverity

MONITOR_SOURCE = "alert-monitor"


@dataclass
class Action:
    kind: str           # "suppress" | "escalate"
    alert_type: str     # e.g. "monitor:spam_detected"
    message: str
    metadata: dict = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _in_window(alert: Alert, window_seconds: int) -> bool:
    if alert.created_at is None:
        return False
    return (_now() - alert.created_at).total_seconds() <= window_seconds


def detect_spam(
    alerts: list[Alert],
    window_seconds: int = 60,
    threshold: int = 10,
) -> list[Action]:
    """Rule 1: Detect repeated identical alerts (same source + alert_type)."""
    # Filter to window, exclude monitor's own alerts
    recent = [
        a for a in alerts
        if _in_window(a, window_seconds) and a.source != MONITOR_SOURCE
    ]

    # Group by (source, alert_type)
    groups: dict[tuple[str, str], int] = defaultdict(int)
    for a in recent:
        groups[(a.source, a.alert_type)] += 1

    actions = []
    for (source, alert_type), count in groups.items():
        if count >= threshold:
            actions.append(Action(
                kind="suppress",
                alert_type="monitor:spam_detected",
                message=f"{count} alerts of type {alert_type} from {source} in {window_seconds}s",
                metadata={"source": source, "alert_type": alert_type, "count": count},
            ))
    return actions


def detect_escalating_rate(
    alerts: list[Alert],
    window_seconds: int = 300,
    buckets: int = 5,
) -> list[Action]:
    """Rule 2: Detect accelerating failure rate per source."""
    recent = [
        a for a in alerts
        if _in_window(a, window_seconds) and a.source != MONITOR_SOURCE
    ]

    # Group by source
    by_source: dict[str, list[Alert]] = defaultdict(list)
    for a in recent:
        by_source[a.source].append(a)

    bucket_size = window_seconds / buckets
    now = _now()
    actions = []

    for source, source_alerts in by_source.items():
        # Bucket alerts
        bucket_counts = [0] * buckets
        for a in source_alerts:
            if a.created_at is None:
                continue
            age = (now - a.created_at).total_seconds()
            bucket_idx = min(int(age / bucket_size), buckets - 1)
            # Invert so bucket 0 = oldest, bucket[-1] = most recent
            bucket_counts[buckets - 1 - bucket_idx] += 1

        # Check if last bucket >= 2x average of prior buckets
        if len(bucket_counts) < 2:
            continue
        prior = bucket_counts[:-1]
        prior_avg = sum(prior) / len(prior) if prior else 0
        last = bucket_counts[-1]

        if prior_avg > 0 and last >= 2 * prior_avg:
            actions.append(Action(
                kind="escalate",
                alert_type="monitor:escalating_rate",
                message=f"Alert rate from {source} escalating: {last} in last bucket vs {prior_avg:.1f} avg",
                metadata={"source": source, "last_bucket": last, "prior_avg": prior_avg},
            ))
    return actions


def detect_critical_signal(alerts: list[Alert]) -> list[Action]:
    """Rule 3: Any emergency-severity alert gets immediately escalated."""
    actions = []
    for a in alerts:
        if a.severity == AlertSeverity.EMERGENCY and a.source != MONITOR_SOURCE:
            actions.append(Action(
                kind="escalate",
                alert_type="monitor:critical_signal",
                message=f"Emergency alert from {a.source}: {a.message}",
                metadata={
                    "source": a.source,
                    "alert_type": a.alert_type,
                    "alert_id": str(a.id),
                },
            ))
    return actions


def detect_unacked_critical(
    alerts: list[Alert],
    stale_minutes: int = 5,
) -> list[Action]:
    """Rule 4: Critical alerts unacknowledged for too long."""
    cutoff = _now() - timedelta(minutes=stale_minutes)
    actions = []
    for a in alerts:
        if (
            a.severity == AlertSeverity.CRITICAL
            and a.acknowledged_at is None
            and a.created_at is not None
            and a.created_at < cutoff
            and a.source != MONITOR_SOURCE
        ):
            actions.append(Action(
                kind="escalate",
                alert_type="monitor:unack_escalation",
                message=f"Unacknowledged critical alert from {a.source}: {a.message}",
                metadata={
                    "source": a.source,
                    "alert_id": str(a.id),
                    "age_minutes": int((_now() - a.created_at).total_seconds() / 60),
                },
            ))
    return actions


def run_all_rules(alerts: list[Alert]) -> list[Action]:
    """Run all detection rules and return combined actions."""
    actions = []
    actions.extend(detect_spam(alerts))
    actions.extend(detect_escalating_rate(alerts))
    actions.extend(detect_critical_signal(alerts))
    actions.extend(detect_unacked_critical(alerts))
    return actions
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/cogos/test_alert_monitor_rules.py -v`
Expected: PASS (11 tests)

**Step 5: Commit**

```bash
git add src/cogos/lib/alert_rules.py tests/cogos/test_alert_monitor_rules.py
git commit -m "feat(alert-monitor): add detection rules engine with 4 rules"
```

---

### Task 5: Action Dispatcher

Deduplicates and executes actions (suppress via alerts capability, escalate via channels capability).

**Files:**
- Create: `src/cogos/lib/alert_dispatcher.py`
- Create: `tests/cogos/test_alert_dispatcher.py`

**Step 1: Write the failing tests**

```python
# tests/cogos/test_alert_dispatcher.py
"""Tests for alert monitor action dispatcher."""

from datetime import datetime, timezone, timedelta
from uuid import uuid4

from cogos.capabilities.alerts import AlertsCapability
from cogos.capabilities.channels import ChannelsCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelType, Process, ProcessStatus
from cogos.db.models.alert import Alert, AlertSeverity
from cogos.lib.alert_rules import Action
from cogos.lib.alert_dispatcher import dispatch_actions


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    proc = Process(name="alert-monitor", status=ProcessStatus.RUNNING, runner="local")
    proc_id = repo.upsert_process(proc)

    # Create supervisor:alerts channel
    ch = Channel(name="supervisor:alerts", owner_process=proc_id, channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    alerts_cap = AlertsCapability(repo, proc_id)
    channels_cap = ChannelsCapability(repo, proc_id)
    return repo, proc_id, alerts_cap, channels_cap


def test_suppress_action_emits_alert(tmp_path):
    repo, proc_id, alerts_cap, channels_cap = _setup(tmp_path)

    # Create system:alerts channel so the alert publish doesn't fail
    ch = Channel(name="system:alerts", owner_process=proc_id, channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    actions = [Action(
        kind="suppress",
        alert_type="monitor:spam_detected",
        message="10 alerts from test-proc",
        metadata={"source": "test-proc", "alert_type": "test:err", "count": 10},
    )]

    dispatch_actions(actions, alerts_cap, channels_cap, existing_alerts=[])

    db_alerts = repo.list_alerts()
    monitor_alerts = [a for a in db_alerts if a.source == "alert-monitor"]
    assert len(monitor_alerts) == 1
    assert monitor_alerts[0].alert_type == "monitor:spam_detected"


def test_escalate_action_sends_to_channel(tmp_path):
    repo, proc_id, alerts_cap, channels_cap = _setup(tmp_path)

    # Create system:alerts channel
    ch = Channel(name="system:alerts", owner_process=proc_id, channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    actions = [Action(
        kind="escalate",
        alert_type="monitor:critical_signal",
        message="Emergency from test-proc",
        metadata={"source": "test-proc", "alert_id": "abc"},
    )]

    dispatch_actions(actions, alerts_cap, channels_cap, existing_alerts=[])

    ch = repo.get_channel_by_name("supervisor:alerts")
    msgs = repo.list_channel_messages(ch.id, limit=10)
    assert len(msgs) == 1
    assert msgs[0].payload["rule"] == "monitor:critical_signal"

    # Also emits a DB alert for dashboard visibility
    db_alerts = repo.list_alerts()
    monitor_alerts = [a for a in db_alerts if a.source == "alert-monitor"]
    assert len(monitor_alerts) == 1


def test_dedup_skips_duplicate_action(tmp_path):
    repo, proc_id, alerts_cap, channels_cap = _setup(tmp_path)

    # Create system:alerts channel
    ch = Channel(name="system:alerts", owner_process=proc_id, channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    # Simulate existing monitor alert in the window
    existing = [Alert(
        severity=AlertSeverity.WARNING,
        alert_type="monitor:spam_detected",
        source="alert-monitor",
        message="already suppressed",
        metadata={"source": "test-proc", "alert_type": "test:err"},
        created_at=datetime.now(timezone.utc),
    )]

    actions = [Action(
        kind="suppress",
        alert_type="monitor:spam_detected",
        message="10 alerts from test-proc",
        metadata={"source": "test-proc", "alert_type": "test:err", "count": 10},
    )]

    dispatch_actions(actions, alerts_cap, channels_cap, existing_alerts=existing)

    db_alerts = repo.list_alerts()
    monitor_alerts = [a for a in db_alerts if a.source == "alert-monitor"]
    assert len(monitor_alerts) == 0  # deduped
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/cogos/test_alert_dispatcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cogos.lib.alert_dispatcher'`

**Step 3: Write the implementation**

```python
# src/cogos/lib/alert_dispatcher.py
"""Alert monitor action dispatcher — executes suppress and escalate actions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from cogos.capabilities.alerts import AlertsCapability
from cogos.capabilities.channels import ChannelsCapability
from cogos.db.models.alert import Alert
from cogos.lib.alert_rules import Action

logger = logging.getLogger(__name__)

DEDUP_WINDOW_SECONDS = 300  # 5 minutes


def _is_duplicate(action: Action, existing_alerts: list[Alert]) -> bool:
    """Check if an equivalent monitor action was already taken in the window."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=DEDUP_WINDOW_SECONDS)
    for alert in existing_alerts:
        if alert.source != "alert-monitor":
            continue
        if alert.alert_type != action.alert_type:
            continue
        if alert.created_at and alert.created_at < cutoff:
            continue
        # Match on key metadata fields (source + alert_type of the original alert)
        meta = alert.metadata or {}
        if (
            meta.get("source") == action.metadata.get("source")
            and meta.get("alert_type") == action.metadata.get("alert_type")
        ):
            return True
        # For unacked/critical, match on alert_id
        if meta.get("alert_id") and meta.get("alert_id") == action.metadata.get("alert_id"):
            return True
    return False


def dispatch_actions(
    actions: list[Action],
    alerts_cap: AlertsCapability,
    channels_cap: ChannelsCapability,
    existing_alerts: list[Alert],
) -> int:
    """Execute actions, skipping duplicates. Returns count of actions taken."""
    taken = 0
    for action in actions:
        if _is_duplicate(action, existing_alerts):
            logger.debug("Skipping duplicate action: %s", action.alert_type)
            continue

        if action.kind == "suppress":
            alerts_cap.warning(action.alert_type, action.message, **action.metadata)
            taken += 1

        elif action.kind == "escalate":
            # Send to supervisor:alerts channel
            channels_cap.send("supervisor:alerts", {
                "rule": action.alert_type,
                "alert_type": action.alert_type,
                "source_process": action.metadata.get("source", "unknown"),
                "summary": action.message,
                "recommended_action": f"investigate {action.metadata.get('source', 'unknown')}",
            })
            # Also emit DB alert for dashboard visibility
            alerts_cap.warning(action.alert_type, action.message, **action.metadata)
            taken += 1

    return taken
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/cogos/test_alert_dispatcher.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add src/cogos/lib/alert_dispatcher.py tests/cogos/test_alert_dispatcher.py
git commit -m "feat(alert-monitor): add action dispatcher with deduplication"
```

---

### Task 6: Alert Monitor Coglet

The daemon coglet that ties everything together. Runs in the Python executor sandbox.

**Files:**
- Create: `images/cogent-v1/apps/alert-monitor/cog.py`
- Create: `images/cogent-v1/apps/alert-monitor/main.py`

**Step 1: Create the coglet config**

```python
# images/cogent-v1/apps/alert-monitor/cog.py
from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    executor="python",
    emoji="\U0001f6a8",
    capabilities=["alerts", "channels", "procs"],
    handlers=["system:alerts"],
)
```

**Step 2: Create the main script**

The Python executor injects `event` (the triggering channel message payload), plus capability objects (`alerts`, `channels`, `procs`) into the sandbox.

```python
# images/cogent-v1/apps/alert-monitor/main.py
# Alert Monitor — daemon Python coglet
# Wakes on each system:alerts message, runs detection rules, dispatches actions.

from cogos.lib.alert_rules import run_all_rules
from cogos.lib.alert_dispatcher import dispatch_actions

# `event` is injected by the Python executor — it's the triggering channel message payload.
# `alerts`, `channels`, `procs` are capability objects injected into sandbox.

# Query recent alerts from DB (stateless — recompute each wake)
recent_alerts = alerts.list(limit=200)

# Run all detection rules
actions = run_all_rules(recent_alerts)

if actions:
    taken = dispatch_actions(actions, alerts, channels, existing_alerts=recent_alerts)
    print(f"Alert monitor: {len(actions)} actions detected, {taken} dispatched")
else:
    print("Alert monitor: no issues detected")
```

**Wait** — the sandbox can't import from `cogos.lib.*` because sandbox code runs with restricted imports. We need to handle this differently.

**Revised approach:** Since the Python executor sandbox doesn't support `import`, the rule functions and dispatcher must be available as capability methods or injected into the sandbox. The cleanest approach: make the alert monitor logic a **capability** that wraps the rules + dispatcher.

Actually, looking at `_execute_python_process` in `handler.py:454-503`, the sandbox executes code via `SandboxExecutor` which has restricted builtins. Let's check what's available.

**Alternative:** Keep `main.py` simple and have it call capability methods. The rules run inside `src/cogos/lib/` and are called by a thin wrapper capability, OR we put all the logic directly in `main.py` as inline code (like `scheduler.py` does — it calls `scheduler.match_messages()` etc.).

**Best approach:** Create an `AlertMonitorCapability` that wraps the rules + dispatcher, exposed to the sandbox as `monitor`. The coglet's `main.py` just calls `monitor.check()`.

**Step 2 (revised): Create AlertMonitorCapability**

```python
# src/cogos/capabilities/alert_monitor.py
"""Alert monitor capability — runs detection rules and dispatches actions."""

from __future__ import annotations

from pydantic import BaseModel

from cogos.capabilities.alerts import AlertsCapability
from cogos.capabilities.base import Capability
from cogos.capabilities.channels import ChannelsCapability
from cogos.lib.alert_dispatcher import dispatch_actions
from cogos.lib.alert_rules import run_all_rules


class CheckResult(BaseModel):
    rules_triggered: int
    actions_taken: int


class AlertMonitorCapability(Capability):
    """Run alert detection rules and dispatch actions.

    Usage:
        monitor.check()
    """

    def check(self) -> CheckResult:
        """Query recent alerts, run detection rules, dispatch actions."""
        # Get alert + channel capabilities scoped to this process
        alerts_cap = AlertsCapability(self.repo, self.process_id)
        channels_cap = ChannelsCapability(self.repo, self.process_id)

        # Query recent alerts from DB
        recent = self.repo.list_alerts(limit=200)

        # Run all detection rules
        actions = run_all_rules(recent)

        # Dispatch actions
        taken = 0
        if actions:
            taken = dispatch_actions(actions, alerts_cap, channels_cap, existing_alerts=recent)

        return CheckResult(rules_triggered=len(actions), actions_taken=taken)
```

**Step 3: Update main.py to use the capability**

```python
# images/cogent-v1/apps/alert-monitor/main.py
# Alert Monitor — daemon Python coglet
# Wakes on each system:alerts message, runs detection rules, dispatches actions.

result = monitor.check()
print(f"Alert monitor: {result.rules_triggered} rules triggered, {result.actions_taken} actions dispatched")
```

**Step 4: Register the capability**

The capability needs to be registered in the DB and wired into the executor's capability setup. Check how existing capabilities like `scheduler` are registered.

We need to:
1. Add `"monitor"` to the capability registry (DB seed)
2. Wire `AlertMonitorCapability` into `_setup_capability_proxies` in the executor
3. Add `"monitor"` to the coglet's capabilities list in `cog.py`
4. Add `"monitor"` to init.py's `_cap_objects`

**Files to modify:**
- `src/cogos/capabilities/alert_monitor.py` (create)
- `images/cogent-v1/apps/alert-monitor/cog.py` (update capabilities)
- `images/cogent-v1/apps/alert-monitor/main.py` (create)
- `src/cogos/executor/handler.py` (add monitor to capability setup)
- `images/cogent-v1/cogos/init.py` (add monitor to _cap_objects)

**Step 5: Write the test**

```python
# tests/cogos/test_alert_monitor_e2e.py
"""End-to-end test for alert monitor coglet."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from cogos.capabilities.alert_monitor import AlertMonitorCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelType, Process, ProcessStatus
from cogos.db.models.alert import AlertSeverity


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    proc = Process(name="alert-monitor", status=ProcessStatus.RUNNING, runner="local")
    proc_id = repo.upsert_process(proc)

    # Create required channels
    for name in ["system:alerts", "supervisor:alerts"]:
        ch = Channel(name=name, owner_process=proc_id, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)

    cap = AlertMonitorCapability(repo, proc_id)
    return repo, proc_id, cap


def test_check_no_alerts(tmp_path):
    repo, proc_id, cap = _setup(tmp_path)
    result = cap.check()
    assert result.rules_triggered == 0
    assert result.actions_taken == 0


def test_check_detects_spam(tmp_path):
    repo, proc_id, cap = _setup(tmp_path)

    # Create 10 identical alerts
    for _ in range(10):
        repo.create_alert(
            severity="warning",
            alert_type="test:noisy",
            source="noisy-proc",
            message="same error",
        )

    result = cap.check()
    assert result.rules_triggered >= 1
    assert result.actions_taken >= 1

    # Verify suppression alert was created
    all_alerts = repo.list_alerts()
    monitor_alerts = [a for a in all_alerts if a.source == "alert-monitor"]
    assert len(monitor_alerts) >= 1


def test_check_escalates_emergency(tmp_path):
    repo, proc_id, cap = _setup(tmp_path)

    repo.create_alert(
        severity="emergency",
        alert_type="system:crash",
        source="critical-proc",
        message="total failure",
    )

    result = cap.check()
    assert result.rules_triggered >= 1
    assert result.actions_taken >= 1

    # Verify escalation was sent to supervisor:alerts channel
    ch = repo.get_channel_by_name("supervisor:alerts")
    msgs = repo.list_channel_messages(ch.id, limit=10)
    assert len(msgs) >= 1


def test_check_deduplicates(tmp_path):
    repo, proc_id, cap = _setup(tmp_path)

    # Create spam alerts
    for _ in range(10):
        repo.create_alert(
            severity="warning",
            alert_type="test:noisy",
            source="noisy-proc",
            message="same error",
        )

    # First check should trigger
    result1 = cap.check()
    assert result1.actions_taken >= 1

    # Second check should dedup
    result2 = cap.check()
    assert result2.actions_taken == 0
```

**Step 6: Run tests**

Run: `python -m pytest tests/cogos/test_alert_monitor_e2e.py -v`
Expected: PASS (4 tests)

**Step 7: Commit**

```bash
git add src/cogos/capabilities/alert_monitor.py images/cogent-v1/apps/alert-monitor/cog.py images/cogent-v1/apps/alert-monitor/main.py tests/cogos/test_alert_monitor_e2e.py
git commit -m "feat(alert-monitor): add AlertMonitorCapability and coglet"
```

---

### Task 7: Wire capability into executor and init

Register the monitor capability so the executor can inject it and init can spawn the coglet.

**Files:**
- Modify: `src/cogos/executor/handler.py` (add alert_monitor to capability proxy setup)
- Modify: `images/cogent-v1/cogos/init.py` (add monitor to `_cap_objects`)

**Step 1: Find capability proxy setup in executor**

Search for where capabilities are mapped in `_setup_capability_proxies` in `src/cogos/executor/handler.py`. Add `AlertMonitorCapability` alongside existing ones.

Add to the capability mapping:
```python
from cogos.capabilities.alert_monitor import AlertMonitorCapability
# In the capability type mapping:
"monitor": AlertMonitorCapability,
```

**Step 2: Add to init.py _cap_objects**

In `images/cogent-v1/cogos/init.py`, add `monitor` to the capability lookup:

```python
_cap_objects = {
    "me": me, "procs": procs, "dir": dir, "file": file,
    "discord": discord, "channels": channels, "secrets": secrets,
    "stdlib": stdlib, "alerts": alerts, "blob": blob, "image": image,
    "asana": asana, "email": email, "github": github,
    "web_search": web_search, "web_fetch": web_fetch, "web": web,
    "cogent": cogent, "history": history,
}
# Add monitor if available
try:
    _cap_objects["monitor"] = monitor
except NameError:
    pass
```

**Step 3: Update cog.py capabilities**

```python
# images/cogent-v1/apps/alert-monitor/cog.py
from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    executor="python",
    emoji="\U0001f6a8",
    capabilities=["monitor"],
    handlers=["system:alerts"],
)
```

**Step 4: Verify all tests pass**

Run: `python -m pytest tests/cogos/ --timeout=30 -x -v`
Expected: All tests pass

**Step 5: Commit**

```bash
git add src/cogos/executor/handler.py images/cogent-v1/cogos/init.py images/cogent-v1/apps/alert-monitor/cog.py
git commit -m "feat(alert-monitor): wire capability into executor and init"
```

---

### Task 8: Final integration test

End-to-end test that simulates the full pipeline: alert emitted → channel message → monitor wakes → actions dispatched.

**Files:**
- Create: `tests/cogos/test_alert_monitor_integration.py`

**Step 1: Write the integration test**

```python
# tests/cogos/test_alert_monitor_integration.py
"""Integration test: full alert pipeline from emit to monitor action."""

from cogos.capabilities.alerts import AlertsCapability
from cogos.capabilities.alert_monitor import AlertMonitorCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelType, Process, ProcessStatus


def test_full_pipeline_spam(tmp_path):
    """Emit 10 alerts -> monitor detects spam -> suppression alert emitted."""
    repo = LocalRepository(str(tmp_path))

    # Set up processes
    emitter = Process(name="noisy-proc", status=ProcessStatus.RUNNING, runner="local")
    emitter_id = repo.upsert_process(emitter)
    monitor_proc = Process(name="alert-monitor", status=ProcessStatus.RUNNING, runner="local")
    monitor_id = repo.upsert_process(monitor_proc)

    # Create system channels
    for name in ["system:alerts", "supervisor:alerts"]:
        ch = Channel(name=name, owner_process=monitor_id, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)

    # Emitter sends 10 alerts
    emitter_alerts = AlertsCapability(repo, emitter_id)
    for i in range(10):
        emitter_alerts.warning("test:noisy", f"error {i}")

    # Verify alerts went to channel
    ch = repo.get_channel_by_name("system:alerts")
    msgs = repo.list_channel_messages(ch.id, limit=100)
    assert len(msgs) == 10

    # Monitor runs
    monitor_cap = AlertMonitorCapability(repo, monitor_id)
    result = monitor_cap.check()

    assert result.rules_triggered >= 1
    assert result.actions_taken >= 1

    # Verify suppression alert exists
    all_alerts = repo.list_alerts()
    monitor_alerts = [a for a in all_alerts if a.source == "alert-monitor"]
    assert len(monitor_alerts) >= 1
    assert any(a.alert_type == "monitor:spam_detected" for a in monitor_alerts)


def test_full_pipeline_emergency(tmp_path):
    """Emit emergency alert -> monitor escalates to supervisor channel."""
    repo = LocalRepository(str(tmp_path))

    emitter = Process(name="critical-proc", status=ProcessStatus.RUNNING, runner="local")
    emitter_id = repo.upsert_process(emitter)
    monitor_proc = Process(name="alert-monitor", status=ProcessStatus.RUNNING, runner="local")
    monitor_id = repo.upsert_process(monitor_proc)

    for name in ["system:alerts", "supervisor:alerts"]:
        ch = Channel(name=name, owner_process=monitor_id, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)

    # Emit emergency
    emitter_alerts = AlertsCapability(repo, emitter_id)
    emitter_alerts.error("system:crash", "total failure")
    # Manually create emergency (AlertsCapability only exposes warning/error=critical)
    repo.create_alert(
        severity="emergency",
        alert_type="system:crash",
        source="critical-proc",
        message="total failure",
    )

    # Monitor runs
    monitor_cap = AlertMonitorCapability(repo, monitor_id)
    result = monitor_cap.check()

    assert result.actions_taken >= 1

    # Verify escalation in supervisor channel
    ch = repo.get_channel_by_name("supervisor:alerts")
    msgs = repo.list_channel_messages(ch.id, limit=10)
    assert len(msgs) >= 1
    assert msgs[0].payload["rule"] == "monitor:critical_signal"
```

**Step 2: Run tests**

Run: `python -m pytest tests/cogos/test_alert_monitor_integration.py -v`
Expected: PASS (2 tests)

**Step 3: Run full test suite**

Run: `python -m pytest tests/cogos/ --timeout=30 -x`
Expected: All tests pass

**Step 4: Commit**

```bash
git add tests/cogos/test_alert_monitor_integration.py
git commit -m "test(alert-monitor): add full pipeline integration tests"
```
