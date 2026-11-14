import { useMemo, useState } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Check, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LineBadge } from "@/landing/LineBadge";
import { FAMILIES, useNetwork, type Route as NetRoute } from "@/lib/network";
import { cn } from "@/lib/utils";
import { app, count, dt, fmt, hhmm, useLoad, type LineReliability } from "../data";
import { lineShape, type Station } from "../lines";
import { LineStrip, type StripRow } from "../LineStrip";
import type { MapLabel } from "../MapView";
import { HourBars, PunctualityBar, SeenBar } from "../Measured";
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
  const rel = useLoad(app.reliability);
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
  const seen = useMemo(() => new Map((rel.data?.lines ?? []).map((l) => [l.routeId, l.trips])), [rel.data]);

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
              Curse din orar văzute în datele live ale Primăriei{rel.data ? `, ${rel.data.recording.label.ro}` : ""}. Cele mai puține, primele.
            </p>
            <Kind k="measured" />
          </div>
          <ul className="-mx-2 mt-3">{bySeen.map(row)}</ul>
          {rel.data && <Method>{rel.data.caveat.ro}</Method>}
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
  const dev = useLoad(app.deviations, "", 60_000);
  const [hover, setHover] = useState<Station | null>(null);
  const [who, setWho] = useState(ROLES[0]);
  const [done, setDone] = useState<string | null>(null);

  const r = net?.byId.get(routeId);
  const shape = net ? lineShape(net, routeId) : null;
  const st = status.data?.lines.find((l) => l.routeId === routeId);
  const flag = missing.data?.routes.find((x) => x.routeId === routeId && x.state === "fara_vehicul");
  const prepared = overview.data?.missingLines.prepared;
  const recorded = prepared?.rows.find((x) => x.routeId === routeId && x.state === "fara_vehicul");
  const m = rel.data?.lines.find((l) => l.routeId === routeId);
  const off = (dev.data?.groups ?? []).filter((g) => g.routeId === routeId && g.classification === "fara_anunt");
  const mine = useMemo(() => (vehicles.data?.features ?? []).filter((v) => v.properties.routeId === routeId), [vehicles.data, routeId]);

  const rows: StripRow[] = useMemo(() => (shape?.stations ?? []).map((s) => {
    const here = mine.filter((v) => v.properties.stopId && s.ids.includes(v.properties.stopId));
    return {
      station: s, mark: "plain" as const,
      chips: here.length ? here.map((v) => {
        const p = v.properties, Arrow = p.directionId === 1 ? ArrowUp : ArrowDown;
        return (
          <span key={p.vehicleId} title={`spre ${p.headsign ?? "capăt"}, raportat la ${hhmm(p.updatedAt)}`}
            className="tabular inline-flex h-6 items-center gap-1 rounded-md bg-foreground px-1.5 text-xs font-medium text-background">
            <Arrow className="size-3" strokeWidth={2.5} />{late(p.delaySec) || "vehicul"}
          </span>
        );
      }) : undefined,
    };
  }), [shape, mine]);
  const placed = rows.reduce((n, x) => n + (Array.isArray(x.chips) ? x.chips.length : 0), 0);
  const track = off[0]?.tracks[0]?.coordinates;

  const layers = useMemo<Layers>(() => {
    if (!shape) return {};
    const a = shape.stations[0], b = shape.stations[shape.stations.length - 1];
    const labels: MapLabel[] = [];
    if (a && b) {
      const horizontal = Math.abs(a.lon - b.lon) * 0.7 >= Math.abs(a.lat - b.lat);
      labels.push({ id: "a", lon: a.lon, lat: a.lat, text: a.name, tone: "stop", place: horizontal ? (a.lon < b.lon ? "left" : "right") : (a.lat > b.lat ? "top" : "bottom") });
      labels.push({ id: "b", lon: b.lon, lat: b.lat, text: b.name, tone: "stop", place: horizontal ? (a.lon < b.lon ? "right" : "left") : (a.lat > b.lat ? "bottom" : "top") });
    }
    if (track?.length) labels.push({ id: "off", lon: track[0][0], lat: track[0][1], text: "abatere de la traseu", tone: "ghost", place: "top" });
    if (hover) labels.push({ id: "hover", lon: hover.lon, lat: hover.lat, text: hover.name, tone: "stop", place: "top" });
    return {
      fit: { key: `line:${routeId}`, points: shape.path },
      highlight: flag ? [] : [routeId], ghost: flag ? [routeId] : [], dim: true,
      detour: track ?? null,
      stops: shape.stations.map((s) => ({ id: s.ids[0], name: s.name, lon: s.lon, lat: s.lat, tone: "served" as const })),
      vehicles: mine.map((v) => ({ id: v.properties.vehicleId, lon: v.geometry.coordinates[0], lat: v.geometry.coordinates[1], routeId })),
      labels,
    };
  }, [shape, mine, hover, flag, routeId, track]);
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
          {back}
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
          <Method>„Fără vehicul în datele live” nu înseamnă că o cursă nu a avut loc. De aceea hotărăște un om, iar CityApp primește semnalul doar după confirmare.</Method>
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
          <p className="tabular text-sm leading-relaxed">
            <span className="font-semibold">{fmt.format(m.trips.observed)} din {count(m.trips.scheduled, "cursă", "curse")}</span> din orar au fost văzute în datele live
            {m.trips.missed > 0 ? <>; <span className="font-semibold text-closure-ink">{fmt.format(m.trips.missed)} nevăzute</span>.</> : "."}
          </p>
          <SeenBar t={m.trips} className="mt-2.5 h-2" />
          {recorded && prepared && (
            <p className="tabular mt-3 text-sm leading-relaxed text-foreground/80">
              {dt(prepared.window.start)}–{hhmm(prepared.window.end)}: {recorded.tripsObserved} din {count(recorded.tripsInService, "cursă", "curse")}.
            </p>
          )}
          <div className="mt-5"><HourBars hours={m.hours} /></div>
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
        <Method>Stațiile sunt în ordinea traseului tur. Săgeata arată sensul vehiculului, iar minutele abaterea față de orar, din datele live.</Method>
      </Section>
    </Panel>
  );
}
