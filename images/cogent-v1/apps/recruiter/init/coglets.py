# Recruiter coglet declarations.
# Each prompt coglet embeds the validate_prompt script; the config coglet embeds
# the validate_config script.  Content is read from the parent apps/recruiter/ dir.

import inspect as _inspect
from pathlib import Path

# __file__ is not set when exec'd by load_image; recover it from the code object.
_THIS_FILE = Path(_inspect.currentframe().f_code.co_filename).resolve()
_APP_DIR = _THIS_FILE.parent.parent


def _read(rel: str) -> str:
    return (_APP_DIR / rel).read_text()


def _read_sourcer(name: str) -> str:
    return (_APP_DIR / "sourcer" / name).read_text()


# ---------------------------------------------------------------------------
# Embedded validation scripts (used as test_command via inline python)
# ---------------------------------------------------------------------------

_VALIDATE_PROMPT = '''\
"""Structural validation for prompt coglets."""
import os, re, sys

def validate(root):
    errors = []
    main_path = os.path.join(root, "main.md")
    if not os.path.exists(main_path):
        errors.append("main.md not found")
        return errors
    with open(main_path) as f:
        content = f.read()
    if len(content.strip()) < 20:
        errors.append("main.md is too short (< 20 chars)")
    if "## " not in content:
        errors.append("main.md has no markdown sections (## headers)")
    blocks = re.findall(r'```python\\n(.*?)```', content, re.DOTALL)
    for i, block in enumerate(blocks):
        try:
            compile(block, f"<code-block-{i}>", "exec")
        except SyntaxError as e:
            errors.append(f"Python syntax error in code block {i}: {e}")
    return errors

errs = validate(os.getcwd())
if errs:
    for e in errs:
        print(f"FAIL: {e}", file=sys.stderr)
    sys.exit(1)
print("PASS")
'''

_VALIDATE_CONFIG = '''\
"""Structural validation for the recruiter config coglet."""
import json, os, sys

def validate(root):
    errors = []
    rubric_path = os.path.join(root, "rubric.json")
    if not os.path.exists(rubric_path):
        errors.append("rubric.json not found")
    else:
        try:
            with open(rubric_path) as f:
                data = json.load(f)
            if not isinstance(data, dict):
                errors.append("rubric.json must be a JSON object")
        except json.JSONDecodeError as e:
            errors.append(f"rubric.json invalid JSON: {e}")
    criteria_path = os.path.join(root, "criteria.md")
    if not os.path.exists(criteria_path):
        errors.append("criteria.md not found")
    else:
        with open(criteria_path) as f:
            content = f.read()
        for section in ["## Must-Have", "## Strong Signals", "## Red Flags"]:
            if section not in content:
                errors.append(f"criteria.md missing section: {section}")
    for name in ["strategy.md", "diagnosis.md"]:
        path = os.path.join(root, name)
        if not os.path.exists(path):
            errors.append(f"{name} not found")
        elif os.path.getsize(path) < 10:
            errors.append(f"{name} is too short")
    for name in ["github.md", "twitter.md", "web.md", "substack.md"]:
        path = os.path.join(root, "sourcer", name)
        if not os.path.exists(path):
            errors.append(f"sourcer/{name} not found")
        elif os.path.getsize(path) < 10:
            errors.append(f"sourcer/{name} is too short")
    return errors

errs = validate(os.getcwd())
if errs:
    for e in errs:
        print(f"FAIL: {e}", file=sys.stderr)
    sys.exit(1)
print("PASS")
'''

# ---------------------------------------------------------------------------
# 1. recruiter-config — data only, no entrypoint
# ---------------------------------------------------------------------------

add_coglet(
    "recruiter-config",
    test_command=f"python -c {repr(_VALIDATE_CONFIG)}",
    files={
        "criteria.md": _read("criteria.md"),
        "rubric.json": _read("rubric.json"),
        "strategy.md": _read("strategy.md"),
        "diagnosis.md": _read("diagnosis.md"),
        "evolution.md": _read("evolution.md"),
        "sourcer/github.md": _read_sourcer("github.md"),
        "sourcer/twitter.md": _read_sourcer("twitter.md"),
        "sourcer/web.md": _read_sourcer("web.md"),
        "sourcer/substack.md": _read_sourcer("substack.md"),
    },
)

# ---------------------------------------------------------------------------
# 2. recruiter-orchestrator — daemon
# ---------------------------------------------------------------------------

add_coglet(
    "recruiter-orchestrator",
    test_command=f"python -c {repr(_VALIDATE_PROMPT)}",
    files={"main.md": _read("recruiter.md")},
    entrypoint="main.md",
    mode="daemon",
    capabilities=[
        "me", "procs", "dir", "file", "discord", "channels", "secrets",
        "stdlib", "coglet_factory", "coglet",
        {"name": "dir", "alias": "data", "config": {"prefix": "data/recruiter/"}},
    ],
)

# ---------------------------------------------------------------------------
# 3. recruiter-discover — one-shot
# ---------------------------------------------------------------------------

add_coglet(
    "recruiter-discover",
    test_command=f"python -c {repr(_VALIDATE_PROMPT)}",
    files={"main.md": _read("discover.md")},
    entrypoint="main.md",
    mode="one_shot",
)

# ---------------------------------------------------------------------------
# 4. recruiter-present — daemon
# ---------------------------------------------------------------------------

add_coglet(
    "recruiter-present",
    test_command=f"python -c {repr(_VALIDATE_PROMPT)}",
    files={"main.md": _read("present.md")},
    entrypoint="main.md",
    mode="daemon",
)

# ---------------------------------------------------------------------------
# 5. recruiter-profile — one-shot
# ---------------------------------------------------------------------------

add_coglet(
    "recruiter-profile",
    test_command=f"python -c {repr(_VALIDATE_PROMPT)}",
    files={"main.md": _read("profile.md")},
    entrypoint="main.md",
    mode="one_shot",
)

# ---------------------------------------------------------------------------
# 6. recruiter-evolve — one-shot
# ---------------------------------------------------------------------------

add_coglet(
    "recruiter-evolve",
    test_command=f"python -c {repr(_VALIDATE_PROMPT)}",
    files={"main.md": _read("evolve.md")},
    entrypoint="main.md",
    mode="one_shot",
)
