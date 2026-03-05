import type {
  StatusResponse,
  Program,
  Session,
  DashboardEvent,
  Trigger,
  MemoryItem,
  Task,
  Channel,
  Alert,
  TimeRange,
} from "./types";

function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("cogent-api-key");
}

function headers(): Record<string, string> {
  const key = getApiKey();
  return key ? { "x-api-key": key } : {};
}

async function fetchJSON<T>(path: string): Promise<T> {
  const resp = await fetch(path, { headers: headers() });
  if (resp.status === 401) throw new Error("unauthorized");
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

export async function getStatus(
  name: string,
  range: TimeRange = "1h",
): Promise<StatusResponse> {
  return fetchJSON(`/api/cogents/${name}/status?range=${range}`);
}

export async function getPrograms(name: string): Promise<Program[]> {
  const r = await fetchJSON<{ programs: Program[] }>(
    `/api/cogents/${name}/programs`,
  );
  return r.programs;
}

export async function getSessions(name: string): Promise<Session[]> {
  const r = await fetchJSON<{ sessions: Session[] }>(
    `/api/cogents/${name}/sessions`,
  );
  return r.sessions;
}

export async function getEvents(
  name: string,
  range: TimeRange = "1h",
): Promise<DashboardEvent[]> {
  const r = await fetchJSON<{ events: DashboardEvent[] }>(
    `/api/cogents/${name}/events?range=${range}`,
  );
  return r.events;
}

export async function getTriggers(name: string): Promise<Trigger[]> {
  const r = await fetchJSON<{ triggers: Trigger[] }>(
    `/api/cogents/${name}/triggers`,
  );
  return r.triggers;
}

export async function getMemory(name: string): Promise<MemoryItem[]> {
  const r = await fetchJSON<{ memory: MemoryItem[] }>(
    `/api/cogents/${name}/memory`,
  );
  return r.memory;
}

export async function getTasks(name: string): Promise<Task[]> {
  const r = await fetchJSON<{ tasks: Task[] }>(
    `/api/cogents/${name}/tasks`,
  );
  return r.tasks;
}

export async function getChannels(name: string): Promise<Channel[]> {
  const r = await fetchJSON<{ channels: Channel[] }>(
    `/api/cogents/${name}/channels`,
  );
  return r.channels;
}

export async function getAlerts(name: string): Promise<Alert[]> {
  const r = await fetchJSON<{ alerts: Alert[] }>(
    `/api/cogents/${name}/alerts`,
  );
  return r.alerts;
}

export async function toggleTriggers(
  name: string,
  ids: string[],
  enabled: boolean,
): Promise<void> {
  await fetch(`/api/cogents/${name}/triggers/toggle`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ ids, enabled }),
  });
}