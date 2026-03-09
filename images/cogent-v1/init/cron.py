"""Cron rules to install on a fresh cogent."""

CRON_RULES = [
    {
        "expression": "* * * * *",
        "event_type": "scheduler:tick",
        "payload": {},
        "enabled": True,
    },
]
