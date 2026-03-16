"""Channel commands — ch ls, ch send, ch log."""

from __future__ import annotations

import json

from cogos.db.models import Channel, ChannelMessage, ChannelType
from cogos.shell.commands import CommandRegistry, ShellState


def register(reg: CommandRegistry) -> None:

    @reg.register("ch", help="Channel commands: ch ls | ch send <name> <json> | ch log <name>")
    def ch(state: ShellState, args: list[str]) -> str:
        if not args:
            return "Usage: ch ls | ch send <name> <json> | ch log <name> [--limit N]"

        subcmd = args[0]

        if subcmd == "ls":
            channels = state.repo.list_channels()
            if not channels:
                return "(no channels)"
            lines = [f"{'NAME':<40} {'TYPE':<12}"]
            lines.append("-" * 54)
            for c in channels:
                lines.append(f"{c.name:<40} {c.channel_type.value:<12}")
            return "\n".join(lines)

        elif subcmd == "send":
            if len(args) < 3:
                return "Usage: ch send <channel> <json-payload>"
            ch_name = args[1]
            # Extract raw JSON from the line to avoid shlex quote stripping
            raw = state.raw_line
            # Find the payload after "ch send <name> "
            marker = ch_name
            idx = raw.find(marker)
            payload_str = raw[idx + len(marker):].strip() if idx >= 0 else " ".join(args[2:])
            try:
                payload = json.loads(payload_str)
            except json.JSONDecodeError as e:
                return f"Invalid JSON: {e}"
            ch_obj = state.repo.get_channel_by_name(ch_name)
            if not ch_obj:
                ch_obj = Channel(name=ch_name, channel_type=ChannelType.NAMED)
                state.repo.upsert_channel(ch_obj)
            msg = ChannelMessage(channel=ch_obj.id, sender_process=None, payload=payload)
            mid = state.repo.append_channel_message(msg)
            return f"Sent to {ch_name} ({mid})"

        elif subcmd == "log":
            if len(args) < 2:
                return "Usage: ch log <channel> [--limit N]"
            ch_name = args[1]
            limit = 20
            if "--limit" in args:
                idx = args.index("--limit")
                if idx + 1 < len(args):
                    limit = int(args[idx + 1])
            ch_obj = state.repo.get_channel_by_name(ch_name)
            if not ch_obj:
                return f"Channel not found: {ch_name}"
            msgs = state.repo.list_channel_messages(ch_obj.id, limit=limit)
            if not msgs:
                return "(no messages)"
            lines = []
            for m in msgs:
                ts = str(m.created_at)[:19] if m.created_at else "?"
                lines.append(f"[{ts}] {json.dumps(m.payload, default=str)}")
            return "\n".join(lines)

        else:
            return f"Unknown subcommand: ch {subcmd}"
