from __future__ import annotations

from pathlib import Path

from cogos.db.local_repository import LocalRepository
from cogos.files.references import extract_file_references, merge_file_references
from cogos.files.store import FileStore


def test_extract_file_references_preserves_order_and_uniqueness() -> None:
    content = """
    intro
    @{alpha/one}
    middle @{beta/two} again @{alpha/one}
    @{ gamma/three }
    """

    assert extract_file_references(content) == [
        "alpha/one",
        "beta/two",
        "gamma/three",
    ]


def test_merge_file_references_filters_self_reference() -> None:
    content = "keep @{shared/base} ignore @{self/file}"

    assert merge_file_references(
        content,
        ["manual/include", "shared/base"],
        exclude_key="self/file",
    ) == ["manual/include", "shared/base"]


def test_new_version_updates_includes(tmp_path: Path) -> None:
    repo = LocalRepository(data_dir=str(tmp_path))
    store = FileStore(repo)
    created = store.create(
        "prompts/root",
        "hello @{shared/base}",
        includes=["shared/base"],
    )

    result = store.new_version(
        "prompts/root",
        "hello @{shared/updated}",
        includes=["shared/updated"],
    )

    assert result is not None
    updated = repo.get_file_by_id(created.id)
    assert updated is not None
    assert updated.includes == ["shared/updated"]
