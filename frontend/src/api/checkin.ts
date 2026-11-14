// CONTRACT v2.25: POST /api/checkin { stickerId, deviceKey }.
// deviceKey is a random id this tab keeps in sessionStorage. The server stores only a salted hash.
import { apiSend, type I18n, type Provenance } from "./client";

export type CheckinAck = {
  routeId: string;
  shortName: string | null;
  directionId: number;
  tripId: string;
  stopId: string | null;
  stopName: string | null;
  method: "position" | "time";
  distanceToRouteMeters: number | null;
  at: string;
  simulated: boolean;
  label: I18n | null;
  provenance: Provenance[];
};

const DEVICE_KEY = "rv-checkin-device";
let memoryId: string | null = null;

function newDeviceId(): string {
  const raw =
    globalThis.crypto?.randomUUID?.() ??
    `rv${Date.now().toString(16)}${Math.random().toString(16).slice(2)}${Math.random().toString(16).slice(2)}`;
  const id = raw.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 64);
  return id.length >= 8 ? id : `rvdevice${Date.now().toString(16)}`;
}

/** One id per tab, reused for every check-in from this page. */
export function deviceKey(): string {
  try {
    const existing = sessionStorage.getItem(DEVICE_KEY);
    if (existing && /^[A-Za-z0-9_-]{8,64}$/.test(existing)) return existing;
    const created = memoryId ?? newDeviceId();
    memoryId = created;
    sessionStorage.setItem(DEVICE_KEY, created);
    return created;
  } catch {
    memoryId ??= newDeviceId();
    return memoryId;
  }
}

export function postCheckin(stickerId: string, key: string) {
  return apiSend<CheckinAck>("POST", "/api/checkin", { stickerId, deviceKey: key });
}
