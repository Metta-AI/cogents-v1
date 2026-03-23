"""Google Sheets capability — create, read, and write spreadsheets."""

from __future__ import annotations

import logging
from typing import Union

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.io.google.auth import get_service

logger = logging.getLogger(__name__)


# ── IO Models ────────────────────────────────────────────────


class SpreadsheetInfo(BaseModel):
    id: str
    title: str
    url: str


class SheetData(BaseModel):
    spreadsheet_id: str
    range: str
    values: list[list[str]]


class WriteResult(BaseModel):
    spreadsheet_id: str
    updated_range: str
    updated_rows: int
    updated_columns: int


class SheetsError(BaseModel):
    error: str


# ── Capability ───────────────────────────────────────────────


class SheetsCapability(Capability):
    """Create, read, and write Google Sheets spreadsheets.

    Usage:
        sheets.create(title="My Sheet")
        sheets.read(spreadsheet_id="...", range="Sheet1!A1:C10")
        sheets.write(spreadsheet_id="...", range="Sheet1!A1", values=[["a","b"],["c","d"]])
    """

    ALL_OPS = {"create", "read", "write"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result: dict = {}

        # "ops": intersection of op sets
        old_ops = existing.get("ops")
        new_ops = requested.get("ops")
        if old_ops is not None and new_ops is not None:
            result["ops"] = set(old_ops) & set(new_ops)
        elif old_ops is not None:
            result["ops"] = old_ops
        elif new_ops is not None:
            result["ops"] = new_ops

        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return

        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            raise PermissionError(
                f"SheetsCapability: '{op}' not allowed (allowed: {allowed_ops})"
            )

    def create(self, title: str) -> Union[SpreadsheetInfo, SheetsError]:
        """Create a new spreadsheet with the given title."""
        self._check("create")
        try:
            svc = get_service("sheets", "v4", self._secrets_provider)
            result = (
                svc.spreadsheets()
                .create(body={"properties": {"title": title}})
                .execute()
            )
            sid = result["spreadsheetId"]
            return SpreadsheetInfo(
                id=sid,
                title=result.get("properties", {}).get("title", title),
                url=f"https://docs.google.com/spreadsheets/d/{sid}",
            )
        except Exception as exc:
            logger.exception("sheets.create failed")
            return SheetsError(error=str(exc))

    def read(
        self, spreadsheet_id: str, range: str = "Sheet1"
    ) -> Union[SheetData, SheetsError]:
        """Read values from a spreadsheet range."""
        self._check("read")
        try:
            svc = get_service("sheets", "v4", self._secrets_provider)
            result = (
                svc.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=range)
                .execute()
            )
            return SheetData(
                spreadsheet_id=spreadsheet_id,
                range=result.get("range", range),
                values=result.get("values", []),
            )
        except Exception as exc:
            logger.exception("sheets.read failed")
            return SheetsError(error=str(exc))

    def write(
        self, spreadsheet_id: str, range: str, values: list[list[str]]
    ) -> Union[WriteResult, SheetsError]:
        """Write values to a spreadsheet range."""
        self._check("write")
        try:
            svc = get_service("sheets", "v4", self._secrets_provider)
            result = (
                svc.spreadsheets()
                .values()
                .update(
                    spreadsheetId=spreadsheet_id,
                    range=range,
                    valueInputOption="USER_ENTERED",
                    body={"values": values},
                )
                .execute()
            )
            return WriteResult(
                spreadsheet_id=spreadsheet_id,
                updated_range=result.get("updatedRange", range),
                updated_rows=result.get("updatedRows", 0),
                updated_columns=result.get("updatedColumns", 0),
            )
        except Exception as exc:
            logger.exception("sheets.write failed")
            return SheetsError(error=str(exc))

    def __repr__(self) -> str:
        return "<SheetsCapability create() read() write()>"
