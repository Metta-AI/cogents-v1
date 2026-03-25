from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cogos.files.context_engine import ContextEngine
from cogos.files.store import FileStore
from dashboard.db import get_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cogos-memory"])


# ── Response models ───────────────────────────────────────────────


class PromptLayer(BaseModel):
    name: str
    content: str
    priority: int


class RenderedPromptResponse(BaseModel):
    prompt: str
    layers: list[PromptLayer]


# ── Routes ────────────────────────────────────────────────────────


@router.get("/memory/rendered", response_model=RenderedPromptResponse)
def get_rendered_memory(
    name: str,
    process_name: str | None = Query(
        None,
        description="Process name to render prompt for. If omitted, returns prompt-relevant file contents.",
    ),
) -> RenderedPromptResponse:
    """Return the fully rendered system prompt.

    If *process_name* is provided, builds the prompt for that specific
    process (resolving all ``@{file-key}`` references).  Otherwise returns
    prompt-relevant files (excluding boot scripts) with a bulk query.
    """
    repo = get_repo()
    file_store = FileStore(repo)
    ctx = ContextEngine(file_store)

    if process_name:
        process = repo.get_process_by_name(process_name)
        if not process:
            raise HTTPException(status_code=404, detail=f"Process not found: {process_name}")

        try:
            full_prompt = ctx.generate_full_prompt(process)
            tree = ctx.resolve_prompt_tree(process)
        except Exception:
            logger.exception("Failed to render prompt for process %s", process_name)
            raise HTTPException(status_code=500, detail=f"Failed to render prompt for {process_name}")

        layers: list[PromptLayer] = []
        for i, node in enumerate(tree):
            layers.append(
                PromptLayer(
                    name=node["key"],
                    content=node["content"],
                    priority=90 - i,  # highest priority first
                )
            )

        return RenderedPromptResponse(prompt=full_prompt, layers=layers)

    # No process specified — return prompt-relevant files (single bulk query),
    # excluding boot scripts which are code, not memory content.
    try:
        file_contents = file_store.list_files_with_content(
            exclude_prefix="mnt/boot/", limit=5000,
        )
    except Exception as exc:
        logger.exception("Failed to list files for memory/rendered")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list files from store: {type(exc).__name__}: {exc}",
        )

    layers = []
    sections: list[str] = []

    for idx, (key, content) in enumerate(file_contents):
        layers.append(
            PromptLayer(
                name=key,
                content=content,
                priority=100 - idx,
            )
        )
        sections.append(f"--- {key} ---\n{content}")

    full_text = "\n\n".join(sections)
    return RenderedPromptResponse(prompt=full_text, layers=layers)
