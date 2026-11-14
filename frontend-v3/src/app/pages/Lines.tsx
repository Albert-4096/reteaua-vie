import { useMemo, useState } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Check, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LineBadge } from "@/landing/LineBadge";
import { FAMILIES, useNetwork, type Route as NetRoute } from "@/lib/network";
import { cn } from "@/lib/utils";
import { app, count, dt, fmt, hhmm, registrySpan, seenByLine, useLoad, weekday, type LineReliability } from "../data";
import { lineShape, type Station } from "../lines";
import { LineStrip, type StripRow } from "../LineStrip";
import type { MapLabel } from "../MapView";
import { HourBars, PunctualityBar, SeenBar } from "../Measured";
import { ReplayBar, ReplayButton, silentLines, useReplay } from "../Replay";
import { link } from "../router";
import { Kind, LiveDot, Loading, Method, Panel, Section, Tag, Title, useMapLayers, type Layers } from "../ui";

const ROLES = ["Dispecer STPT", "Biroul de mobilitate, Primărie", "Comunicare STPT"];
const MODE: Record<string, string> = { tramvai: "Tramvai", troleibuz: "Troleibuz", autobuz: "Autobuz" };
const late = (sec: number | null) => (sec == null ? "" : Math.abs(sec) < 60 ? "la timp" : `${sec > 0 ? "+" : "−"}${Math.round(Math.abs(sec) / 60)} min`);
/** Above 15 min of median delay the trip matching is suspect, so we show trips seen and keep quiet about punctuality. */
const trusted = (p: LineReliability["punctuality"]) => p.conclusive && p.medianSec != null && Math.abs(p.medianSec) <= 900;

/** The 58 lines. Point at one to see where it runs; open it for its stations, its vehicles and what we recorded. */
export function Lines({ routeId }: { routeId?: string }) {
  return routeId ? <Line key={routeId} routeId={routeId} /> : <LineList />;
}

function LineList() {
  const net = useNetwork();
  const status = useLoad(app.linesStatus);
  const missing = useLoad(app.missing, "", 60_000);
  const vehicles = useLoad(app.vehicles, "", 15_000);
  const reg = useLoad(app.registry);
  const [q, setQ] = useState("");
  const [order, setOrder] = useState<"seen" | "type">("seen");
  const [hover, setHover] = useState<string | null>(null);

  const live = useMemo(() => {
    const m = new Map<string, number>();
    for (const v of vehicles.data?.features ?? []) m.set(v.properties.routeId, (m.get(v.properties.routeId) ?? 0) + 1);
    return m;
  }, [vehicles.data]);
  const noVehicle = useMemo(() => new Set((missing.data?.routes ?? []).filter((r) => r.state === "fara_vehicul").map((r) => r.routeId)), [missing.data]);
  const state = useMemo(() => new Map((status.data?.lines ?? []).map((l) => [l.routeId, l])), [status.data]);
  const seen = useMemo(() => seenByLine(reg.data), [reg.data]);

  const layers = useMemo<Layers>(() => ({
    fit: { key: "city" },
    highlight: hover ? [hover] : [],
    ghost: [...noVehicle].filter((r) => r !== hover),
    vehicles: (vehicles.data?.features ?? []).filter((v) => !hover || v.properties.routeId === hover)
      .map((v) => ({ id: v.properties.vehicleId, lon: v.geometry.coordinates[0], lat: v.geometry.coordinates[1], routeId: v.properties.routeId })),
  }), [hover, noVehicle, vehicles.data]);
  useMapLayers(layers);

  const needle = q.trim().toLowerCase();
  const routes = (net?.routes ?? []).filter((r) => !needle || r.shortName.toLowerCase().startsWith(needle) || r.longName.toLowerCase().includes(needle));
  const bySeen = useMemo(() => [...routes].sort((a, b) => (seen.get(a.id)?.share ?? 2) - (seen.get(b.id)?.share ?? 2) || (seen.get(b.id)?.missed ?? 0) - (seen.get(a.id)?.missed ?? 0)), [routes, seen]);

  const row = (r: NetRoute) => {
    const t = seen.get(r.id);
    const st = state.get(r.id);
    return (
      <li key={r.id}>
        <a {...link({ page: "linii", routeId: r.id })} onPointerEnter={() => setHover(r.id)} onPointerLeave={() => setHover(null)} onFocus={() => setHover(r.id)} onBlur={() => setHover(null)}
          className="flex min-h-12 items-center gap-3 rounded-lg px-2 py-1.5 outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring">
          <LineBadge routeId={r.id} size="lg" />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm">{r.longName}</span>
            {(noVehicle.has(r.id) || (st && st.state !== "normala") || live.get(r.id)) && (
              <span className="tabular block truncate text-xs text-muted-foreground">
                {noVehicle.has(r.id) ? <span className="font-medium text-closure-ink">fără vehicul în datele live acum</span> : st && st.state !== "normala" ? st.label.ro : `${count(live.get(r.id)!, "vehicul", "vehicule")} acum`}
              </span>
            )}
          </span>
          {t && t.scheduled > 0 && (
            <span className="w-[5.5rem] shrink-0 text-right">
              <span className={cn("tabular block text-sm", t.missed > 0 ? "font-semibold text-foreground" : "text-muted-foreground")}>{fmt.format(t.observed)} din {fmt.format(t.scheduled)}</span>
              <SeenBar t={t} className="mt-1" />
            </span>
          )}
        </a>
      </li>
    );
  };

  return (
    <Panel
      head={
        <>
          <Title sub={net ? <span className="tabular">{count(net.routes.length, "linie", "linii")} · {vehicles.data ? `${count(vehicles.data.features.length, "vehicul", "vehicule")} în datele live acum` : "se citesc vehiculele…"}</span> : "Se încarcă rețeaua…"}>Linii</Title>
          <div className="mt-4 flex gap-2">
            <label className="relative block min-w-0 flex-1">
              <span className="sr-only">Caută o linie</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Număr sau capăt de linie" type="search"
                className="h-10 w-full rounded-lg border bg-background pl-9 pr-3 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/40" />
            </label>
            <div role="group" aria-label="Ordinea listei" className="flex shrink-0 rounded-lg bg-muted p-0.5 text-sm">
              {([["seen", "Curse văzute"], ["type", "Tip"]] as const).map(([k, label]) => (
                <button key={k} type="button" aria-pressed={order === k} onClick={() => setOrder(k)}
                  className={cn("rounded-md px-2.5 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring", order === k ? "bg-card font-medium shadow-xs" : "text-muted-foreground hover:text-foreground")}>{label}</button>
              ))}
            </div>
          </div>
        </>
      }
    >
      {!net ? <Loading rows={6} /> : routes.length === 0 ? <p className="text-sm text-muted-foreground">Nicio linie nu se potrivește cu „{q}”.</p> : order === "seen" ? (
        <>
          <div className="flex items-start justify-between gap-4">
            <p className="text-sm leading-snug text-muted-foreground">
              Curse din orar la care am văzut un vehicul în datele live ale Primăriei{reg.data ? ` (${registrySpan(reg.data)})` : ""}. Cele mai puține, primele.
            </p>
            <Kind k="measured" />
          </div>
          <ul className="-mx-2 mt-3">{bySeen.map(row)}</ul>
          <Method>Din registrul zilnic al curselor, înregistrat la 15 secunde. Estimare din datele live, nu raportul oficial; nu arată nicio vină a cuiva și nu e o clasificare a curselor: doar SMTT le încadrează.</Method>
        </>
      ) : FAMILIES.map((f) => {
        const rs = routes.filter(f.test);
        return rs.length ? <Section key={f.id} title={f.label} aside={rs.length}><ul className="-mx-2">{rs.map(row)}</ul></Section> : null;
      })}
    </Panel>
  );
}

function Line({ routeId }: { routeId: string }) {
  const net = useNetwork();
  const status = useLoad(app.linesStatus);
  const missing = useLoad(app.missing, "", 60_000);
  const overview = useLoad(app.overview);
  const vehicles = useLoad(app.vehicles, "", 15_000);
  const rel = useLoad(app.reliability);
  const reg = useLoad(app.registry);
  const dev = useLoad(app.deviations, "", 60_000);
  const [hover, setHover] = useState<Station | null>(null);
  const [who, setWho] = useState(ROLES[0]);
  const [done, setDone] = useState<string | null>(null);
  const replay = useReplay();

  const r = net?.byId.get(routeId);
  const shape = net ? lineShape(net, routeId) : null;
  const st = status.data?.lines.find((l) => l.routeId === routeId);
  const flag = missing.data?.routes.find((x) => x.routeId === routeId && x.state === "fara_vehicul");
  const prepared = overview.data?.missingLines.prepared;
  const recorded = prepared?.rows.find((x) => x.routeId === routeId && x.state === "fara_vehicul");
  const m = rel.data?.lines.find((l) => l.routeId === routeId);
  const off = (dev.data?.groups ?? []).filter((g) => g.routeId === routeId && g.classification === "fara_anunt");
  const mine = useMemo(() => (vehicles.data?.features ?? []).filter((v) => v.properties.routeId === routeId), [vehicles.data, routeId]);
  // the line day by day, from the daily registry: one mixed total would hide a day with no vehicle at all
  const days = useMemo(() => (reg.data?.entries ?? []).flatMap((e) => {
    const l = e.lines.find((x) => x.routeId === routeId);
    if (!l || !e.recording.firstAt || !e.recording.lastAt) return [];
    const whole = hhmm(e.recording.firstAt) <= "00:01" && hhmm(e.recording.lastAt) >= "23:58";
    return [{ date: e.date, final: e.final, span: !e.final ? "în curs" : whole ? "toată ziua" : `${hhmm(e.recording.firstAt)}–${hhmm(e.recording.lastAt)}`, seen: Math.min(l.tripsSeen, l.tripsScheduledInRecording), scheduled: l.tripsScheduledInRecording, vehicles: l.vehiclesSeen ?? null }];
  }), [reg.data, routeId]);
  const empty = [...days].reverse().find((d) => d.final && d.scheduled > 0 && d.seen === 0);
  // one total on the page: the sum of the day rows (the registry), never a second count from another endpoint
  const total = useMemo(() => {
    const scheduled = days.reduce((n, d) => n + d.scheduled, 0), observed = days.reduce((n, d) => n + d.seen, 0);
    return scheduled > 0 ? { scheduled, observed, missed: scheduled - observed, share: observed / scheduled } : null;
  }, [days]);

  // minutes of delay only where punctuality is trusted for the line: otherwise a mismatched trip would print "+49 min"
  const showDelay = !!m && trusted(m.punctuality);
  const rows: StripRow[] = useMemo(() => (shape?.stations ?? []).map((s) => {
    const here = mine.filter((v) => v.properties.stopId && s.ids.includes(v.properties.stopId));
    return {
      station: s, mark: "plain" as const,
      chips: here.length ? here.map((v) => {
        const p = v.properties, Arrow = p.directionId === 1 ? ArrowUp : ArrowDown;
        return (
          <span key={p.vehicleId} title={`spre ${p.headsign ?? "capăt"}, raportat la ${hhmm(p.updatedAt)}`}
            className="tabular inline-flex h-6 items-center gap-1 rounded-md bg-foreground px-1.5 text-xs font-medium text-background">
            <Arrow className="size-3" strokeWidth={2.5} />{(showDelay && late(p.delaySec)) || "vehicul"}
          </span>
        );
      }) : undefined,
    };
  }), [shape, mine, showDelay]);
  const placed = rows.reduce((n, x) => n + (Array.isArray(x.chips) ? x.chips.length : 0), 0);
  const track = off[0]?.tracks[0]?.coordinates;

  // dashed when the live data has no vehicle of the line: right now, or, in the replay, on the whole recorded day
  const quiet = replay.on ? silentLines(reg.data, replay.data).includes(routeId) : !!flag;
  const still = useMemo<Layers>(() => {
    if (!shape) return {};
    const a = shape.stations[0], b = shape.stations[shape.stations.length - 1];
    const labels: MapLabel[] = [];
    if (a && b) {
      const horizontal = Math.abs(a.lon - b.lon) * 0.7 >= Math.abs(a.lat - b.lat);
      labels.push({ id: "a", lon: a.lon, lat: a.lat, text: a.name, tone: "stop", place: horizontal ? (a.lon < b.lon ? "left" : "right") : (a.lat > b.lat ? "top" : "bottom") });
      labels.push({ id: "b", lon: b.lon, lat: b.lat, text: b.name, tone: "stop", place: horizontal ? (a.lon < b.lon ? "right" : "left") : (a.lat > b.lat ? "bottom" : "top") });
    }
    if (track?.length && !replay.on) labels.push({ id: "off", lon: track[0][0], lat: track[0][1], text: "abatere de la traseu", tone: "ghost", place: "top" });
    if (hover) labels.push({ id: "hover", lon: hover.lon, lat: hover.lat, text: hover.name, tone: "stop", place: "top" });
    return {
      fit: { key: `line:${routeId}`, points: shape.path },
      highlight: quiet ? [] : [routeId], ghost: quiet ? [routeId] : [], dim: true,
      detour: replay.on ? null : track ?? null,
      stops: shape.stations.map((s) => ({ id: s.ids[0], name: s.name, lon: s.lon, lat: s.lat, tone: "served" as const })),
      labels,
    };
  }, [shape, hover, quiet, routeId, track, replay.on]);
  // now: this line's vehicles; in the replay: every vehicle of that minute, so the street around the line is seen moving
  const now = useMemo(() => mine.map((v) => ({ id: v.properties.vehicleId, lon: v.geometry.coordinates[0], lat: v.geometry.coordinates[1], routeId })), [mine, routeId]);
  const layers = useMemo<Layers>(() => (still.fit ? { ...still, vehicles: replay.on ? replay.vehicles : now, recorded: replay.on ? { stepMs: replay.stepMs } : null } : still), [still, now, replay.on, replay.vehicles, replay.stepMs]);
  useMapLayers(layers);

  const triage = async (d: "confirmat" | "respins") => {
    try { await app.triage(routeId, missing.data!.window, d, who); setDone(d); } catch (e) { setDone(`Nu s-a salvat (${(e as Error).message}). Încercați din nou.`); }
  };

  const back = (
    <a {...link({ page: "linii" })} className="-ml-1 inline-flex items-center gap-1 rounded-md px-1 text-sm text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
      <ArrowLeft className="size-3.5" /> Linii
    </a>
  );
  if (!net) return <Panel head={back}><Loading rows={5} /></Panel>;
  if (!r) return <Panel head={back}><p className="text-sm text-muted-foreground">Linia {routeId} nu există în orarul curent.</p></Panel>;

  return (
    <Panel
      head={
        <>
          <div className="flex items-center justify-between gap-3">{back}<ReplayButton r={replay} /></div>
          <ReplayBar r={replay} line={{ routeId, shortName: r.shortName }} />
          <div className="mt-2.5 flex items-start gap-3">
            <LineBadge routeId={routeId} size="lg" />
            <div className="min-w-0">
              <h1 className="text-lg font-semibold leading-snug tracking-tight">{r.longName}</h1>
              <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
                {MODE[st?.mode ?? ""] ?? "Linie"} · {shape ? count(shape.stations.length, "stație", "stații") : "traseu indisponibil"}
                {flag ? <Tag tone="closure">fără vehicul în datele live</Tag> : st && st.state !== "normala" ? <Tag>{st.label.ro}</Tag> : null}
              </p>
            </div>
          </div>
        </>
      }
    >
      {flag && missing.data && (
        <section className="mb-8 rounded-xl border border-foreground/25 px-4 pb-4 pt-3.5 shadow-card">
          <p className="text-base font-semibold leading-snug">Circulă linia {r.shortName}?</p>
          <p className="tabular mt-1.5 text-sm leading-relaxed text-muted-foreground">
            Între {hhmm(missing.data.window.start)} și {hhmm(missing.data.window.end)} orarul are {count(flag.tripsInService, "cursă", "curse")}. În datele live ale Primăriei am văzut {flag.tripsObserved}.
            {flag.firstMissedTrip ? ` Prima: ${hhmm(flag.firstMissedTrip.scheduledTime)}, ${flag.firstMissedTrip.stopName}.` : ""}
          </p>
          <p className="mt-1.5 text-sm font-medium leading-relaxed">Fie linia nu circulă, fie vehiculele nu trimit date. Din date nu se poate ști; hotărăște un om.</p>
          {done === "confirmat" || done === "respins" ? (
            <p className="mt-3 flex items-center gap-1.5 text-sm font-medium text-accent-foreground"><Check className="size-4" />{done === "confirmat" ? "Confirmat. Semnalul poate pleca spre CityApp." : "Respins. Nu pleacă nimic."}</p>
          ) : (
            <>
              <label className="mt-3 flex items-center gap-2 text-sm">
                <span className="text-muted-foreground">Răspund ca</span>
                <select value={who} onChange={(e) => setWho(e.target.value)} className="h-9 min-w-0 flex-1 rounded-lg border bg-background px-2.5 font-medium outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40">
                  {ROLES.map((x) => <option key={x}>{x}</option>)}
                </select>
              </label>
              <div className="mt-2.5 grid grid-cols-2 gap-2">
                <Button variant="outline" className="h-10 rounded-lg" onClick={() => triage("confirmat")}>Nu circulă</Button>
                <Button variant="outline" className="h-10 rounded-lg" onClick={() => triage("respins")}>Circulă, lipsesc date</Button>
              </div>
              {done && <p role="alert" className="mt-2.5 text-sm text-closure-ink">{done}</p>}
            </>
          )}
          <Method>Semnalul intră în fluxul pe care CityApp îl poate citi doar după confirmare.</Method>
        </section>
      )}

      {off.map((g) => (
        <section key={g.firstAt} className="mb-8 rounded-xl border border-foreground/25 px-4 py-3.5 shadow-card">
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-base font-semibold leading-snug">Posibilă abatere de la traseu <Tag>de verificat</Tag></p>
          <p className="tabular mt-1.5 text-sm leading-relaxed text-muted-foreground">
            La {hhmm(g.firstAt)}, {count(g.trips, "cursă", "curse")} din {g.tripsSeen} văzute {g.trips === 1 ? "a mers" : "au mers"} până la {fmt.format(g.maxDistanceM)} m de traseu{g.street ? `, pe ${g.street}` : ""}{g.nearStop ? `, lângă ${g.nearStop}` : ""}. Nu am găsit un anunț; poate fi și o cursă spre depou. Urma e pe hartă, cu linie întreruptă.
          </p>
        </section>
      ))}

      {m && m.trips.scheduled > 0 && rel.data && (
        <Section title="Orarul față de stradă" aside={<Kind k="measured" />}>
          {empty ? (
            <p className="text-sm leading-relaxed">
              <span className="font-semibold">{weekday(empty.date)[0].toUpperCase() + weekday(empty.date).slice(1)}</span>: <span className="font-semibold text-closure-ink">niciun vehicul al liniei în datele live</span>, {empty.span}. Orarul publicat are {count(empty.scheduled, "cursă", "curse")}.
            </p>
          ) : (
            <p className="tabular text-sm leading-relaxed">
              <span className="font-semibold">{fmt.format((total ?? m.trips).observed)} din {count((total ?? m.trips).scheduled, "cursă", "curse")}</span> din orar au fost văzute în datele live
              {(total ?? m.trips).missed > 0 ? <>; <span className="font-semibold text-closure-ink">{fmt.format((total ?? m.trips).missed)} nevăzute</span>.</> : "."}
            </p>
          )}
          {days.length > 0 ? (
            <ul className="mt-3 divide-y border-y">
              {days.map((d) => (
                <li key={d.date} className="flex items-center gap-3 py-2 text-sm">
                  <span className="w-[7.5rem] shrink-0"><span className="block font-medium">{new Date(d.date).toLocaleDateString("ro-RO", { weekday: "short", day: "numeric", month: "short", timeZone: "Europe/Bucharest" })}</span><span className="tabular block text-xs text-muted-foreground">{d.span}</span></span>
                  {d.scheduled > 0 ? (
                    <>
                      <SeenBar t={{ scheduled: d.scheduled, observed: d.seen, missed: d.scheduled - d.seen, share: d.seen / d.scheduled }} className="h-2 flex-1" />
                      <span className="tabular w-24 shrink-0 whitespace-nowrap text-right">
                        <span className={cn("block", d.seen < d.scheduled ? "font-semibold" : "text-muted-foreground")}>{fmt.format(d.seen)} din {fmt.format(d.scheduled)}</span>
                        {d.vehicles != null && <span className="block text-xs text-muted-foreground">{d.vehicles === 0 ? "niciun vehicul" : count(d.vehicles, "vehicul", "vehicule")}</span>}
                      </span>
                    </>
                  ) : <span className="flex-1 text-right text-muted-foreground">încă necomparat</span>}
                </li>
              ))}
            </ul>
          ) : <SeenBar t={m.trips} className="mt-2.5 h-2" />}
          {recorded && prepared && !empty && (
            <p className="tabular mt-3 text-sm leading-relaxed text-foreground/80">
              {dt(prepared.window.start)}–{hhmm(prepared.window.end)}: {recorded.tripsObserved} din {count(recorded.tripsInService, "cursă", "curse")}.
            </p>
          )}
          {days.length > 0 && <p className="mt-2 text-xs leading-relaxed text-muted-foreground">Pe zile: curse din orar, în orele înregistrate, la care am văzut un vehicul{days.some((d) => d.vehicles != null) ? ", și câte vehicule diferite au apărut pe linie în datele live" : ""}. Din registrul zilnic al curselor (Rapoarte).</p>}
          <p className="mt-5 text-xs text-muted-foreground">Pe ore, toate zilele înregistrate la un loc:</p>
          <div className="mt-2"><HourBars hours={m.hours} /></div>
          {trusted(m.punctuality) && (
            <div className="mt-6">
              <PunctualityBar p={m.punctuality} />
              {m.headway.medianRealMin != null && m.headway.medianSchedMin != null && (
                <p className="tabular mt-1.5 text-sm text-muted-foreground">Interval între vehicule: {fmt.format(m.headway.medianRealMin)} min pe stradă, {fmt.format(m.headway.medianSchedMin)} min în orar.</p>
              )}
            </div>
          )}
          <Method>{rel.data.recording.label.ro[0].toUpperCase() + rel.data.recording.label.ro.slice(1)}. {rel.data.caveat.ro}</Method>
        </Section>
      )}

      {st?.closureId && st.closureTitle && (
        <Section title="Lucrare pe traseu">
          <a {...link({ page: "lucrare", id: st.closureId, tab: "impact" })} className="-mx-2 flex items-center gap-3 rounded-lg px-2 py-2 text-sm outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring">
            <span className="size-2.5 shrink-0 rounded-full bg-closure" aria-hidden />
            <span className="min-w-0 flex-1 font-medium leading-snug">{st.closureTitle.ro}</span>
            <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
          </a>
        </Section>
      )}

      <Section title="Traseu" aside={<span className="inline-flex items-center gap-2">{mine.length > 0 && <LiveDot />}{count(mine.length, "vehicul", "vehicule")} acum</span>}>
        {!shape ? <p className="text-sm text-muted-foreground">Orarul nu dă traseul acestei linii.</p> : <LineStrip color={`#${r.color}`} rows={rows} fold={false} onHover={setHover} />}
        {mine.length > placed && <Method>{count(mine.length - placed, "vehicul e", "vehicule sunt")} între stații sau pe sensul opus; le vedeți pe hartă.</Method>}
        <Method>Stațiile sunt în ordinea traseului tur. Săgeata arată sensul vehiculului{showDelay ? ", iar minutele abaterea față de orar, din datele live." : ". Abaterea față de orar nu e arătată pentru această linie: potrivirea curselor cu orarul e în verificare."}</Method>
      </Section>
    </Panel>
  );
}
