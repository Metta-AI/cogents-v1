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
