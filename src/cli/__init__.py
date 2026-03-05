"""Shared CLI utilities."""

from __future__ import annotations

import click


def get_cogent_name(ctx: click.Context) -> str:
    """Return the cogent name from the root context."""
    obj = ctx.find_root().obj
    name = obj.get("cogent_id") if obj else None
    if not name:
        raise click.UsageError("No cogent specified. Use: cogent <name> <command> or set COGENT_ID env var.")
    return name
