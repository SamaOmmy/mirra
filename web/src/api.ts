export class Unauthorized extends Error {}
/** The PC answered (e.g. through Tailscale HTTPS) but the mirror server on it is not running. */
export class ServerDown extends Error {}

export interface Settings {
  monitor: number;
  fps: number;
  quality: number;
  scale: number;
  cursor: boolean;
}

export interface ServerState {
  seq: number;
  tick: number;
  viewers: number;
  error: string;
  width: number;
  height: number;
  capture: string;
  version: string;
  update?: { latest: string; url: string } | null;
  settings: Settings;
  audio?: { enabled: boolean; listeners: number; recording: boolean };
}

export interface MonitorInfo {
  index: number;
  width: number;
  height: number;
  label: string;
}

export interface MonitorsResponse {
  monitors: MonitorInfo[];
  limits: { fps: [number, number]; quality: [number, number]; scale: [number, number] };
  max_clients: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { credentials: "same-origin", cache: "no-store", ...init });
  if (r.status === 401 && path !== "/api/login") throw new Unauthorized();
  if (r.status === 502 || r.status === 503 || r.status === 504) throw new ServerDown();
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error ?? `${r.status} ${r.statusText}`);
  return body as T;
}

const post = (path: string, data: unknown) =>
  request<any>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

export const api = {
  state: () => request<ServerState>("/api/state"),
  monitors: () => request<MonitorsResponse>("/api/monitors"),
  login: (token: string) => post("/api/login", { token }),
  logout: () => post("/api/logout", {}),
  settings: (changes: Partial<Settings>) => post("/api/settings", changes) as Promise<Settings>,
};
