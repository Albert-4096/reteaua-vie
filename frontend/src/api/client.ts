// Thin client for the real /api (D-011: no mock). Types come from the backend OpenAPI (`pnpm types`).
import type { components } from "./schema";

type S = components["schemas"];
export type Analysis = S["Analysis"] & { decisionGroups?: DecisionGroup[] | null };
export type AffectedStop = S["AffectedStop"];
export type Impact = S["Impact"];
export type Closure = S["Closure"] & { id: string; status: string; locationNote?: S["I18n"] | null };
export type GeneratedNotice = S["GeneratedNotice"];
export type PublishResult = S["PublishResult"];
export type Alert = S["Alert"];
export type FeedValidation = S["FeedValidation"];
export type Provenance = S["Provenance"];
export type I18n = S["I18n"];
export type Network = S["Network"];
export type CaseSummary = S["CaseSummary"];
export type Health = S["Health"];
export type Job = S["Job"];
export type ClosureSummary = S["ClosureSummary"];

type RowRef = { stopId: string; routeId: string; directionId: number };

/** Optional, added by ticket T2: one human question for many unsure rows. */
export type DecisionGroup = {
  id: string;
  routeId: string;
  question: I18n;
  reason?: I18n | null;
  /** "affected" = the platform suggests „nu oprește”; null = no suggestion. */
  suggested?: "affected" | "served" | null;
  rows?: RowRef[];
  rowKeys?: (string | RowRef)[];
};

export type Decision = { stopId: string; routeId: string; directionId: number; confirmed: boolean };

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

async function parse<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T;
  let code = "HTTP_" + res.status;
  let message = res.statusText;
  try {
    const body = await res.json();
    code = body?.error?.code ?? code;
    message = body?.error?.message ?? message;
  } catch {
    /* not JSON */
  }
  throw new ApiError(res.status, code, message);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Paths marked J in the contract may answer 202 { jobId }: poll /api/jobs/{id} every second. */
async function settle<T>(res: Response, onPending?: () => void): Promise<T> {
  if (res.status !== 202) return parse<T>(res);
  const { jobId } = (await res.json()) as { jobId: string };
  onPending?.();
  for (;;) {
    await sleep(1000);
    const job = await parse<Job>(await fetch(`/api/jobs/${encodeURIComponent(jobId)}`));
    if (job.state === "done") return job.result as T;
    if (job.state === "error") throw new ApiError(500, job.error?.code ?? "JOB_ERROR", job.error?.message ?? "job failed");
  }
}

export async function apiGet<T>(path: string, onPending?: () => void): Promise<T> {
  return settle<T>(await fetch(path, { headers: { Accept: "application/json" } }), onPending);
}

export async function apiSend<T>(method: "POST" | "PATCH", path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return settle<T>(res);
}

const enc = encodeURIComponent;
export const api = {
  health: () => apiGet<Health>("/api/health"),
  network: () => apiGet<Network>("/api/network"),
  zones: () => apiGet<GeoJSON.FeatureCollection>("/api/zones"),
  cases: () => apiGet<CaseSummary[]>("/api/cases"),
  closures: () => apiGet<ClosureSummary[]>("/api/closures"),
  closure: (id: string) => apiGet<Closure>(`/api/closures/${enc(id)}`),
  analysis: (id: string) => apiGet<Analysis>(`/api/closures/${enc(id)}/analysis`),
  impact: (id: string) => apiGet<Impact>(`/api/closures/${enc(id)}/impact`),
  notice: (id: string) => apiGet<GeneratedNotice>(`/api/closures/${enc(id)}/notice`),
  validation: (id: string) => apiGet<FeedValidation>(`/api/closures/${enc(id)}/validation`),
  alerts: () => apiGet<Alert[]>("/api/feed/alerts.json"),
  decide: (id: string, decisions: Decision[]) =>
    apiSend<Analysis>("PATCH", `/api/closures/${enc(id)}/stops`, { decisions }),
  publish: (id: string) => apiSend<PublishResult>("POST", `/api/closures/${enc(id)}/publish`),
  audioUrl: (id: string, stopId: string) => `/api/closures/${enc(id)}/audio/${enc(stopId)}.mp3`,
  posterUrl: (id: string, stopId: string) => `/api/closures/${enc(id)}/poster.pdf?stopId=${enc(stopId)}`,
};
