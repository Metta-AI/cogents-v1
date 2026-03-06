"use client";

import { Badge } from "@/components/shared/Badge";
import { fmtTimestamp } from "@/lib/format";
import type { DashboardEvent } from "@/lib/types";

interface ChannelDetailProps {
  channelName: string;
  events: DashboardEvent[];
}

export function ChannelDetail({ channelName, events }: ChannelDetailProps) {
  const filtered = events.filter((e) => e.source === channelName);

  return (
    <div>
      <h3 className="text-[var(--text-primary)] text-sm font-semibold mb-3">
        Channel: {channelName}
      </h3>
      {filtered.length === 0 ? (
        <p className="text-[var(--text-muted)] text-[13px]">
          No events for this channel.
        </p>
      ) : (
        <div className="space-y-1">
          {filtered.map((evt) => (
            <div
              key={String(evt.id)}
              className="flex items-center gap-3 px-3 py-2 rounded bg-[var(--bg-elevated)] border border-[var(--border)] text-[13px]"
            >
              <Badge variant="info">{evt.event_type ?? "event"}</Badge>
              <span className="text-[var(--text-secondary)]">
                {evt.source ?? "--"}
              </span>
              <span className="ml-auto text-[var(--text-muted)] text-[11px]">
                {fmtTimestamp(evt.created_at)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
