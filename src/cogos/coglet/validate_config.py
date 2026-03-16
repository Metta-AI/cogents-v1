"""Structural validation for the recruiter config coglet."""
import json
import os
import sys


def validate(root: str) -> list[str]:
    """Validate the recruiter config coglet. Returns list of error strings."""
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


if __name__ == "__main__":
    errs = validate(os.getcwd())
    if errs:
        for e in errs:
            print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    print("PASS")
