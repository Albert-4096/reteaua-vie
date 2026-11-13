// A small request cache shared by the steps: one fetch per key, explicit refresh after a write.
import { useEffect, useSyncExternalStore } from "react";
import { ApiError } from "../api/client";

type Entry = { data?: unknown; error?: ApiError; loading: boolean; pending: boolean; promise?: Promise<void> };

const entries = new Map<string, Entry>();
const listeners = new Set<() => void>();
let version = 0;

function emit() {
  version++;
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

function toApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError(0, "NETWORK", e instanceof Error ? e.message : String(e));
}

export function load(key: string, fetcher: (onPending: () => void) => Promise<unknown>, force = false) {
  const cur = entries.get(key);
  if (cur && !force && (cur.loading || cur.data !== undefined || cur.error)) return;
  const entry: Entry = { data: cur?.data, loading: true, pending: false };
  entries.set(key, entry);
  entry.promise = fetcher(() => {
    entry.pending = true;
    emit();
  })
    .then((data) => {
      entries.set(key, { data, loading: false, pending: false });
    })
    .catch((e) => {
      entries.set(key, { loading: false, pending: false, error: toApiError(e) });
    })
    .finally(emit);
  emit();
}

export function setData(key: string, data: unknown) {
  entries.set(key, { data, loading: false, pending: false });
  emit();
}

/** Drop cached keys that start with any prefix, so the next render refetches them. */
export function invalidate(...prefixes: string[]) {
  for (const k of [...entries.keys()]) if (prefixes.some((p) => k.startsWith(p))) entries.delete(k);
  emit();
}

export type Resource<T> = { data?: T; error?: ApiError; loading: boolean; pending: boolean };

export function useResource<T>(key: string | null, fetcher: (onPending: () => void) => Promise<T>): Resource<T> {
  useSyncExternalStore(subscribe, () => version);
  useEffect(() => {
    if (key) load(key, fetcher);
  });
  if (!key) return { loading: false, pending: false };
  const e = entries.get(key);
  if (!e) return { loading: true, pending: false };
  return { data: e.data as T | undefined, error: e.error, loading: e.loading, pending: e.pending };
}
