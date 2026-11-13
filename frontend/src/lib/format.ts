// Romanian formatting for numbers and times. Times are shown in Europe/Bucharest whatever the browser zone.
import i18n from "../i18n";

const TZ = "Europe/Bucharest";
const locale = () => (i18n.language === "en" ? "en-GB" : "ro-RO");

export function fmtNumber(n: number | null | undefined): string | null {
  if (n === null || n === undefined || Number.isNaN(n)) return null;
  return new Intl.NumberFormat(locale(), { maximumFractionDigits: 0 }).format(n);
}

function parts(iso: string) {
  const d = new Date(iso);
  const get = (o: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat(locale(), { timeZone: TZ, ...o }).format(d);
  return { d, get };
}

/** 08.11.2026, 12:00 */
export function fmtDateTime(iso: string): string {
  const { get } = parts(iso);
  const date = get({ day: "2-digit", month: "2-digit", year: "numeric" }).replace(/\//g, ".");
  const time = get({ hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  return `${date}, ${time}`;
}

/** 8 noiembrie 2026 */
export function fmtDate(iso: string): string {
  return parts(iso).get({ day: "numeric", month: "long", year: "numeric" });
}

export function fmtTime(iso: string): string {
  return parts(iso).get({ hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
}

function sameDay(a: string, b: string) {
  return fmtDate(a) === fmtDate(b);
}

/** „8 noiembrie 2026, 10:00–18:00” or „2 noiembrie 2026, 00:00 – 31 decembrie 2026, 23:59” */
export function fmtWindow(w: { start: string; end: string }): string {
  if (sameDay(w.start, w.end)) return `${fmtDate(w.start)}, ${fmtTime(w.start)}–${fmtTime(w.end)}`;
  return `${fmtDate(w.start)}, ${fmtTime(w.start)} – ${fmtDate(w.end)}, ${fmtTime(w.end)}`;
}

export function fmtMeters(m: number | null | undefined): string | null {
  if (m === null || m === undefined) return null;
  return `${fmtNumber(Math.round(m))} m`;
}

export function tr(text: { ro: string; en?: string | null } | null | undefined): string {
  if (!text) return "";
  return i18n.language === "en" && text.en ? text.en : text.ro;
}
