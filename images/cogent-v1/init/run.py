"""Processes to create when initializing a cogent."""

PROCESSES = [
    {
        "process": {
            "name": "scheduler",
            "mode": "daemon",
            "content": "CogOS scheduler daemon",
            "runner": "lambda",
            "priority": 100.0,
            "status": "waiting",
        },
        "code_key": "cogos/scheduler",
        "capabilities": [
            "scheduler/match_events",
            "scheduler/select_processes",
            "scheduler/dispatch_process",
            "scheduler/unblock_processes",
            "scheduler/kill_process",
        ],
        "handlers": [
            "scheduler:tick",
        ],
    },
]
