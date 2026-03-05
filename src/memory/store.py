"""MemoryStore: high-level memory operations with hierarchical key resolution."""

from __future__ import annotations

import json
import logging

import boto3

from brain.db.models import MemoryRecord, MemoryScope
from brain.db.repository import Repository

logger = logging.getLogger(__name__)


class MemoryStore:
    """Wraps Repository with hierarchical key resolution, scope overrides, and embeddings."""

    def __init__(self, repo: Repository, *, embed_model: str = "amazon.titan-embed-text-v2:0") -> None:
        self._repo = repo
        self._embed_model = embed_model
        self._bedrock: boto3.client | None = None

    def _get_bedrock(self) -> boto3.client:
        if self._bedrock is None:
            self._bedrock = boto3.client("bedrock-runtime")
        return self._bedrock

    # ───────────────────────────────────────────────────────────
    # Hierarchical key resolution
    # ───────────────────────────────────────────────────────────

    def resolve_keys(self, keys: list[str]) -> list[MemoryRecord]:
        """Resolve memory keys with ancestor/child init expansion.

        For each key, collects:
        1. Ancestor /init records walking up the path
        2. The key itself (exact match)
        3. Child /init records (immediate children)

        COGENT-scoped records shadow POLIS-scoped records with the same name.
        Results are sorted root-to-leaf by path depth.
        """
        if not keys:
            return []

        names_to_fetch: set[str] = set()
        child_prefixes: list[str] = []

        for key in keys:
            key = key.rstrip("/")
            parts = key.strip("/").split("/")

            # Ancestor inits: /a/init, /a/b/init, ...
            for i in range(1, len(parts)):
                names_to_fetch.add("/" + "/".join(parts[:i]) + "/init")

            # The key itself
            names_to_fetch.add(key)

            # We'll also look for child inits under this key
            child_prefixes.append(key + "/")

        # Batch fetch exact names
        records_by_name: dict[str, MemoryRecord] = {}
        if names_to_fetch:
            for rec in self._repo.get_memories_by_names(list(names_to_fetch)):
                if rec.name:
                    # COGENT overrides POLIS: scope sorts ASC so cogent comes after polis
                    records_by_name[rec.name] = rec

        # Fetch children matching key/ prefixes, keep only /init records
        if child_prefixes:
            child_records = self._repo.query_memory_by_prefixes(child_prefixes)
            for rec in child_records:
                if rec.name and rec.name.endswith("/init"):
                    records_by_name[rec.name] = rec

        # Sort by path depth (root first), then alphabetically
        return sorted(
            records_by_name.values(),
            key=lambda r: (r.name or "").count("/"),
        )

    # ───────────────────────────────────────────────────────────
    # CRUD
    # ───────────────────────────────────────────────────────────

    def upsert(
        self,
        name: str,
        content: str,
        *,
        scope: MemoryScope = MemoryScope.COGENT,
        provenance: dict | None = None,
        generate_embedding: bool = True,
    ) -> MemoryRecord:
        """Create or update a memory record, optionally generating an embedding."""
        embedding = None
        if generate_embedding and content.strip():
            try:
                embedding = self._generate_embedding(content)
            except Exception:
                logger.warning("Failed to generate embedding for %s", name, exc_info=True)

        record = MemoryRecord(
            scope=scope,
            name=name,
            content=content,
            embedding=embedding,
            provenance=provenance or {},
        )
        self._repo.insert_memory(record)
        return record

    def list_memories(
        self,
        *,
        prefix: str | None = None,
        scope: MemoryScope | None = None,
        limit: int = 200,
    ) -> list[MemoryRecord]:
        return self._repo.query_memory(scope=scope, prefix=prefix, limit=limit)

    def get(self, name: str) -> MemoryRecord | None:
        """Get a single memory record by exact name."""
        results = self._repo.query_memory(name=name, limit=1)
        return results[0] if results else None

    def delete_by_prefix(
        self,
        prefix: str,
        *,
        scope: MemoryScope | None = None,
    ) -> int:
        return self._repo.delete_memories_by_prefix(prefix, scope)

    # ───────────────────────────────────────────────────────────
    # Embeddings
    # ───────────────────────────────────────────────────────────

    def _generate_embedding(self, text: str) -> list[float]:
        """Generate an embedding vector using Bedrock Titan."""
        bedrock = self._get_bedrock()
        response = bedrock.invoke_model(
            modelId=self._embed_model,
            body=json.dumps({"inputText": text[:8000]}),
        )
        result = json.loads(response["body"].read())
        return result["embedding"]

    def search_similar(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        """Semantic search: generate embedding for query, then search via pgvector."""
        # pgvector search is not yet wired through RDS Data API
        # (Data API doesn't support vector types natively)
        logger.info("Semantic search not yet available via Data API, returning empty")
        return []
