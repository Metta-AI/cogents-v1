"""File and FileVersion models — versioned hierarchical store."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class FileVersion(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    file_id: UUID  # FK -> File.id
    version: int
    read_only: bool = False
    content: str = ""
    source: str = "cogent"
    is_active: bool = True
    run_id: UUID | None = None  # FK -> Run.id (which run created this version)
    created_at: datetime | None = None


class File(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    key: str  # hierarchical path, e.g. "vsm/s1/do-content"
    includes: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
