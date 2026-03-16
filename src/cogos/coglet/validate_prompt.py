"""Structural validation for prompt coglets."""
import os
import re
import sys


def validate(root: str) -> list[str]:
    """Validate a prompt coglet directory. Returns list of error strings (empty = pass)."""
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
    # Validate inline Python code blocks
    blocks = re.findall(r'```python\n(.*?)```', content, re.DOTALL)
    for i, block in enumerate(blocks):
        try:
            compile(block, f"<code-block-{i}>", "exec")
        except SyntaxError as e:
            errors.append(f"Python syntax error in code block {i}: {e}")
    return errors


if __name__ == "__main__":
    errs = validate(os.getcwd())
    if errs:
        for e in errs:
            print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    print("PASS")
