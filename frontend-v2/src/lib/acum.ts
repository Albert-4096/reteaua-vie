// "Acum": what is wrong on the network right now, on the real clock.
// One issue model for every layout, so a number has one label and one value everywhere.
import { api, nf, useLoad, type ClosureSummary, type Missing, type MissingRoute, type Network, type Overview, type Route } from "./api";

export type Level = 3 | 2 | 1 | 0;

export type Issue = {
  id: string;
  kind: "line" | "works";
  level: Level;
  statusLabel: string;
  title: string; // "Linia 23"
  subtitle: string; // route long name or works title
  lines: Route[];
  /** what the timetable promises vs what the street shows: the product's mechanism */
  planned: { value: string; label: string };
  actual: { value: string; label: string };
  facts: { label: string; value: string }[];
  announced: boolean;
  announcedNote: string;
  since: string | null;
  routeIds: string[];
  focusStopId?: string;
  closureId?: string;
  source: string;
};

export type Acum = {
  at: string;
  windowLabel: string;
  issues: Issue[];
  kpis: { id: string; label: string; value: string; hint: string; level: Level }[];
  network: Network;
  missing: Missing;
  overview: Overview;
};

const hm = new Intl.DateTimeFormat("ro-RO", { timeZone: "Europe/Bucharest", hour: "2-digit", minute: "2-digit" });
const t = (iso: string) => hm.format(new Date(iso));

function lineIssue(r: MissingRoute, routes: Map<string, Route>, win: Missing["window"]): Issue {
  const none = r.state === "fara_vehicul";
  const route = routes.get(r.routeId);
  const announced = r.decision?.decision === "confirmat";
  return {
    id: `line:${r.routeId}`,
    kind: "line",
    level: none ? 3 : 2,
    statusLabel: none ? "Fără vehicul în date" : "Vehicule lipsă",
    title: `Linia ${r.shortName}`,
    subtitle: r.longName.replace(" - ", " – "),
    lines: route ? [route] : [],
    planned: { value: nf.format(r.tripsInService), label: r.tripsInService === 1 ? "cursă în orar" : "curse în orar" },
    actual: none
      ? { value: "0", label: "vehicule văzute" }
      : { value: nf.format(r.tripsObserved), label: r.tripsObserved === 1 ? "cursă cu vehicul" : "curse cu vehicul" },
    facts: [
      r.firstMissedTrip
        ? { label: "Prima cursă fără vehicul", value: `${t(r.firstMissedTrip.scheduledTime)}, ${r.firstMissedTrip.stopName}` }
        : { label: "Prima cursă fără vehicul", value: "—" },
      { label: "Ultimul vehicul văzut", value: r.lastSeenAt ? t(r.lastSeenAt) : `niciunul din ${t(win.start)}` },
      { label: "Zile înregistrate la fel", value: r.repeatedDays ? String(r.repeatedDays) : "—" },
    ],
    announced,
    announcedNote: announced ? "confirmat de dispecerat" : "neconfirmat, neanunțat",
    since: r.since,
    routeIds: [r.routeId],
    focusStopId: r.firstMissedTrip?.stopId,
    source: "Orar SMTT GTFS 4.31 față de vehiculele din API-ul Primăriei, înregistrate la 15 s",
  };
}

function shortWorksTitle(t: string) {
  const head = t.split(",")[0];
  const i = head.lastIndexOf(" – ");
  return i > 0 ? `Lucrări, ${head.slice(i + 3)}` : head;
}

function worksIssue(c: ClosureSummary, routes: Map<string, Route>, ghostToday: number | null, only: boolean): Issue {
  const lines = c.routeIds.map((id) => routes.get(id)).filter((r): r is Route => !!r);
  const names = lines.map((l) => l.shortName).join(", ");
  return {
    id: `works:${c.id}`,
    kind: "works",
    level: 2,
    statusLabel: "Linii deviate",
    title: shortWorksTitle(c.title.ro),
    subtitle: `${lines.length} linii deviate: ${names}`,
    lines,
    planned: { value: only && ghostToday != null ? nf.format(ghostToday) : "—", label: "plecări în orar azi, în stațiile închise" },
    actual: { value: "0", label: "au loc" },
    facts: [
      { label: "Stații fără niciun mijloc de transport", value: c.stopsSuspended != null ? nf.format(c.stopsSuspended) : "—" },
      { label: "Perioada", value: `din ${new Date(c.window.start).toLocaleDateString("ro-RO", { day: "numeric", month: "short" })}, până la finalizarea lucrărilor` },
    ],
    announced: c.status === "published",
    announcedNote: c.reconstructed ? "anunțat de STPT (reconstituit)" : "publicat",
    since: c.window.start,
    routeIds: c.routeIds,
    closureId: c.id,
    source: "Anunț STPT 11060 și orarul SMTT GTFS",
  };
}

export function useAcum() {
  const net = useLoad(api.network);
  const miss = useLoad(api.missing);
  const ov = useLoad(api.overviewNow);
  const error = net.error ?? miss.error ?? ov.error;
  if (!net.data || !miss.data || !ov.data) return { acum: null as Acum | null, error };

  const routes = new Map(net.data.routes.map((r) => [r.id, r]));
  const m = miss.data;
  const o = ov.data;
  const lineIssues = m.status === "ok" ? m.routes.map((r) => lineIssue(r, routes, m.window)) : [];
  const works = o.activeClosures.map((c) => worksIssue(c, routes, o.ghostDeparturesToday, o.activeClosures.length === 1));
  const issues = [...lineIssues, ...works].sort((a, b) => b.level - a.level || Number(a.announced) - Number(b.announced));

  const noVeh = m.byMode.reduce((s, x) => s + x.tripsWithNoVehicle, 0);
  const sched = m.byMode.reduce((s, x) => s + x.tripsScheduled, 0);
  const kpis: Acum["kpis"] = [
    { id: "lines", label: "Linii fără vehicul", value: nf.format(m.routes.filter((r) => r.state === "fara_vehicul").length), hint: "ultima oră", level: 3 },
    { id: "trips", label: "Curse fără vehicul", value: nf.format(noVeh), hint: `din ${nf.format(sched)} în orar, ultima oră`, level: 2 },
    { id: "ghost", label: "Plecări pierdute azi", value: o.ghostDeparturesToday != null ? nf.format(o.ghostDeparturesToday) : "—", hint: "în stațiile închise de lucrări", level: 2 },
    { id: "veh", label: "Vehicule pe traseu", value: o.vehiclesLive != null ? nf.format(o.vehiclesLive) : "—", hint: o.vehiclesAt ? `la ${t(o.vehiclesAt)}` : "", level: 0 },
  ];
  return {
    acum: {
      at: m.window.end,
      windowLabel: `${t(m.window.start)}–${t(m.window.end)}`,
      issues,
      kpis,
      network: net.data,
      missing: m,
      overview: o,
    } satisfies Acum,
    error,
  };
}

export const LEVEL_WORD: Record<Level, string> = { 3: "Fără serviciu", 2: "Serviciu redus", 1: "Informare", 0: "Normal" };
