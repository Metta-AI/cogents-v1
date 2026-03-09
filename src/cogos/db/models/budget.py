"""Budget model — token and cost accounting per period."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class BudgetPeriod(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class Budget(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    period: BudgetPeriod
    period_start: date
    tokens_spent: int = 0
    cost_spent_usd: Decimal = Decimal("0")
    token_limit: int = 0
    cost_limit_usd: Decimal = Decimal("0")
    created_at: datetime | None = None
    updated_at: datetime | None = None
