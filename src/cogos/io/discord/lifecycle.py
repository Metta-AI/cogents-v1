"""Manage Discord roles and webhooks for cogent personas."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import discord

logger = logging.getLogger(__name__)

ROLE_PREFIX = "cogent:"


@dataclass
class CogentPersona:
    """Runtime state for a cogent's Discord persona."""
    cogent_name: str
    display_name: str = ""
    avatar_url: str = ""
    color: int = 0
    default_channels: list[str] = field(default_factory=list)
    role_id: int | None = None
    webhooks: dict[int, discord.Webhook] = field(default_factory=dict)  # channel_id -> webhook


class LifecycleManager:
    """Ensure Discord roles and webhooks exist for each cogent."""

    def __init__(self):
        self._personas: dict[str, CogentPersona] = {}

    @property
    def personas(self) -> dict[str, CogentPersona]:
        return self._personas

    def get_persona(self, cogent_name: str) -> CogentPersona | None:
        return self._personas.get(cogent_name)

    def role_name(self, cogent_name: str) -> str:
        return f"{ROLE_PREFIX}{cogent_name}"

    async def sync(self, guild: discord.Guild, configs: list) -> None:
        """Sync roles and webhooks for all cogents in a guild.

        configs is a list of CogentDiscordConfig from registry.py.
        """
        await self._sync_roles(guild, configs)
        await self._sync_webhooks(guild, configs)

    async def _sync_roles(self, guild: discord.Guild, configs: list) -> None:
        """Create/update mentionable roles for each cogent."""
        existing_roles = {r.name: r for r in guild.roles if r.name.startswith(ROLE_PREFIX)}
        desired_names = {self.role_name(c.cogent_name) for c in configs}

        for cfg in configs:
            rname = self.role_name(cfg.cogent_name)
            if rname in existing_roles:
                role = existing_roles[rname]
                if role.color.value != cfg.color:
                    try:
                        await role.edit(color=discord.Color(cfg.color))
                    except Exception:
                        logger.warning("Failed to update role color for %s", rname, exc_info=True)
            else:
                try:
                    role = await guild.create_role(
                        name=rname,
                        color=discord.Color(cfg.color),
                        mentionable=True,
                        reason="Cogent Discord persona",
                    )
                    logger.info("Created role %s (id=%s) in guild %s", rname, role.id, guild.name)
                except Exception:
                    logger.exception("Failed to create role %s in guild %s", rname, guild.name)
                    continue

            persona = self._personas.setdefault(cfg.cogent_name, CogentPersona(
                cogent_name=cfg.cogent_name,
                display_name=cfg.display_name,
                avatar_url=cfg.avatar_url,
                color=cfg.color,
                default_channels=cfg.default_channels,
            ))
            persona.role_id = role.id
            persona.display_name = cfg.display_name
            persona.avatar_url = cfg.avatar_url
            persona.color = cfg.color
            persona.default_channels = cfg.default_channels

        # Delete roles for removed cogents
        for rname, role in existing_roles.items():
            if rname not in desired_names:
                try:
                    await role.delete(reason="Cogent removed")
                    logger.info("Deleted role %s from guild %s", rname, guild.name)
                    # Remove persona
                    cogent_name = rname[len(ROLE_PREFIX):]
                    self._personas.pop(cogent_name, None)
                except Exception:
                    logger.warning("Failed to delete role %s", rname, exc_info=True)

    async def _sync_webhooks(self, guild: discord.Guild, configs: list) -> None:
        """Index existing cogent webhooks. New webhooks are created on-demand via get_or_create_webhook."""
        for channel in guild.text_channels:
            try:
                existing_webhooks = await channel.webhooks()
            except discord.Forbidden:
                continue
            except Exception:
                continue

            for wh in existing_webhooks:
                if wh.name and wh.name.startswith("cogent-"):
                    cogent_name = wh.name[len("cogent-"):]
                    persona = self._personas.get(cogent_name)
                    if persona:
                        persona.webhooks[channel.id] = wh

    async def get_or_create_webhook(self, channel: discord.TextChannel, cogent_name: str) -> discord.Webhook | None:
        """Get existing webhook or create one on-demand for a cogent in a channel."""
        persona = self._personas.get(cogent_name)
        if not persona:
            return None

        # Check cache first
        if channel.id in persona.webhooks:
            return persona.webhooks[channel.id]

        wh_name = f"cogent-{cogent_name}"
        try:
            existing = await channel.webhooks()
            for wh in existing:
                if wh.name == wh_name:
                    persona.webhooks[channel.id] = wh
                    return wh

            if len(existing) >= 15:
                logger.warning("Webhook limit in #%s, skipping %s", channel.name, cogent_name)
                return None

            wh = await channel.create_webhook(
                name=wh_name,
                reason=f"Cogent persona: {persona.display_name}",
            )
            persona.webhooks[channel.id] = wh
            logger.info("Created webhook %s in #%s", wh_name, channel.name)
            return wh
        except Exception:
            logger.warning("Failed to get/create webhook %s in #%s", wh_name, channel.name, exc_info=True)
            return None
