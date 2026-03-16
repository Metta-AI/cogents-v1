"""Live E2E test: create coglet on dr.alpha, patch it, verify."""

import os
os.environ["USE_LOCAL_DB"] = "1"

from cogos.db.factory import create_repository
from cogos.capabilities.coglet_factory import CogletFactoryCapability
from cogos.capabilities.coglet import CogletCapability
from uuid import uuid4


def test_coglet_e2e_live():
    repo = create_repository()
    pid = uuid4()

    # 1. Create a coglet
    factory = CogletFactoryCapability(repo, pid)
    result = factory.create(
        name="hello-coglet",
        test_command="python tests/test_hello.py",
        files={
            "src/hello.py": "def greet(name):\n    return f'Hello, {name}!'\n",
            "tests/test_hello.py": (
                "exec(open('src/hello.py').read())\n"
                "assert greet('World') == 'Hello, World!'\n"
                "print('PASS')\n"
            ),
        },
    )
    print(f"\nCreated: id={result.coglet_id}, name={result.name}, test_passed={result.test_passed}")
    print(f"Test output: {result.test_output}")
    assert result.test_passed

    # 2. Inspect via tendril
    tendril = CogletCapability(repo, pid)
    tendril._scope = {"coglet_id": result.coglet_id}

    files = tendril.list_files()
    print(f"Files: {files}")
    assert "src/hello.py" in files

    status = tendril.get_status()
    print(f"Status: version={status.version}, patches={status.patch_count}")
    assert status.version == 0

    # 3. Propose a patch that adds a farewell function
    diff = (
        "--- a/src/hello.py\n"
        "+++ b/src/hello.py\n"
        "@@ -1,2 +1,5 @@\n"
        " def greet(name):\n"
        "     return f'Hello, {name}!'\n"
        "+\n"
        "+def farewell(name):\n"
        "+    return f'Goodbye, {name}!'\n"
        "--- a/tests/test_hello.py\n"
        "+++ b/tests/test_hello.py\n"
        "@@ -1,3 +1,5 @@\n"
        " exec(open('src/hello.py').read())\n"
        " assert greet('World') == 'Hello, World!'\n"
        "+assert farewell('World') == 'Goodbye, World!'\n"
        " print('PASS')\n"
    )
    patch = tendril.propose_patch(diff)
    print(f"Patch: id={patch.patch_id}, test_passed={patch.test_passed}")
    print(f"Patch output: {patch.test_output}")
    assert patch.test_passed

    # 4. Merge
    merge = tendril.merge_patch(patch.patch_id)
    print(f"Merge: merged={merge.merged}, new_version={merge.new_version}")
    assert merge.merged
    assert merge.new_version == 1

    # 5. Verify
    content = tendril.read_file("src/hello.py")
    print(f"After merge, has farewell: {'farewell' in content}")
    assert "farewell" in content

    status = tendril.get_status()
    print(f"Final: version={status.version}, patches={status.patch_count}")
    assert status.version == 1
    assert status.patch_count == 0

    # 6. Run tests on new main
    test_result = tendril.run_tests()
    print(f"Main tests pass: {test_result.passed}")
    assert test_result.passed

    print("\nE2E LIVE TEST PASSED")
