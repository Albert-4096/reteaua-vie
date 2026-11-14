import { useMemo, useState } from "react";
import { ArrowRight, Check, Download, ExternalLink, FileText, Radio, Route, Network, QrCode, Megaphone, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LineBadge } from "@/landing/LineBadge";
import { api, fmt, hhmm, useApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { app, day, dt, type AnalysisStop, type ClosureSummary, type DecisionGroup } from "./data";
import { MapView, type MapStop } from "./MapView";
import { Split } from "./App";
import { go } from "./router";
import { Count, Figure, Kind, Loading, Method, Problem, Section, Tag } from "./ui";

const statusTag = (c: Pick<ClosureSummary, "status" | "reconstructed">) =>
  c.status === "published" ? <Tag tone="green">{c.reconstructed ? "Publicată (reconstituit)" : "Publicată"}</Tag>
    : c.status === "analyzed" ? <Tag tone="ink">Analizată, nepublicată</Tag> : <Tag>{c.status}</Tag>;

const uniq = <T,>(xs: T[]) => [...new Set(xs)];

/* ---------------- shared data for one closure ---------------- */
function useClosureMap(closureId: string) {
  const closure = useApi(() => app.closure(closureId), undefined, closureId);
  const analysis = useApi(() => app.analysis(closureId), undefined, closureId);
  const stops: MapStop[] = useMemo(() => {
    const seen = new Set<string>();
    return (analysis.data?.stops ?? []).filter((s) => !seen.has(s.stopId) && seen.add(s.stopId))
      .map((s) => ({ id: s.stopId, name: s.name, lon: s.location[0], lat: s.location[1], tone: s.state === "affected" ? "closed" : "unsure" }));
  }, [analysis.data]);
  const map = (
    <MapView closures={closure.data ? [{ id: closure.data.id, geometry: closure.data.geometry, selected: true }] : []}
      highlight={closure.data?.routeIds ?? []} stops={stops} fitTo={closure.data ? closureId : undefined} />
  );
  return { closure, analysis, map };
}

function ClosureHead({ c }: { c: ClosureSummary | null }) {
  if (!c) return <div className="px-6 py-6"><Loading rows={2} /></div>;
  return (
    <div className="px-6 pb-2 pt-6">
      <div className="flex flex-wrap items-center gap-2">{statusTag(c)}{c.routeIds.map((r) => <LineBadge key={r} routeId={r} />)}</div>
      <h2 className="mt-3 text-xl font-semibold leading-snug tracking-tight">{c.title.ro}</h2>
      <p className="tabular mt-1 text-sm text-muted-foreground">{dt(c.window.start)} – {dt(c.window.end)}</p>
      {c.reconstructedNote && <p className="mt-1 text-xs text-muted-foreground">{c.reconstructedNote.ro}</p>}
    </div>
  );
}

function Next({ to, label }: { to: Parameters<typeof go>[0]; label: string }) {
  return (
    <div className="sticky bottom-0 border-t bg-card/95 px-6 py-4 backdrop-blur">
      <Button className="h-11 w-full rounded-lg text-[0.95rem]" onClick={() => go(to)}>{label} <ArrowRight className="size-4" /></Button>
    </div>
  );
}

/* ---------------- 1. Ansamblu ---------------- */
export function Overview() {
  const o = useApi(app.overview);
  const missing = useApi(app.missing, 60000);
  const vehicles = useApi(api.vehicles, 15000);
  const ids = (o.data?.activeClosures ?? []).map((c) => c.id);
  const geos = useApi(() => (ids.length ? Promise.all(ids.map((id) => app.closure(id))) : Promise.resolve(null)), undefined, ids.join());
  const conflicts = useApi(() => (ids.length ? Promise.all(ids.map((id) => app.conflicts(id))).then((xs) => xs.flat()) : Promise.resolve(null)), undefined, ids.join());
  const pairs = uniq((conflicts.data ?? []).map((c) => [c.closureId, c.otherClosureId].sort().join("|")))
    .map((k) => conflicts.data!.find((c) => [c.closureId, c.otherClosureId].sort().join("|") === k)!);
  const noVehicle = (missing.data?.routes ?? []).filter((r) => r.state === "fara_vehicul");

  const panel = (
    <>
      <div className="grid grid-cols-3 gap-4 px-6 py-6">
        <Figure value={o.data ? o.data.activeClosures.length : "–"} label="lucrări active" />
        <Figure value={o.data ? fmt.format(o.data.ghostDeparturesToday) : "–"} label="plecări pierdute azi" tone="closure" kind="estimate" />
        <Figure value={vehicles.data ? fmt.format(vehicles.data.features.length) : "–"} label="vehicule în datele live" note={vehicles.data?.features[0] ? `acum, ${hhmm(vehicles.data.features[0].properties.updatedAt!)}` : undefined} />
      </div>
      <Section title="Lucrări active" aside={o.data ? `${o.data.activeClosures.length} acum` : undefined}>
        {!o.data ? <Loading /> : (
          <ul className="-mx-2 space-y-1">
            {o.data.activeClosures.map((c) => (
              <li key={c.id}>
                <button type="button" onClick={() => go("planifici", c.id)} className="w-full rounded-lg px-2 py-3 text-left transition-colors hover:bg-muted">
                  <div className="flex items-center gap-2">{statusTag(c)}{c.routeIds.slice(0, 6).map((r) => <LineBadge key={r} routeId={r} />)}{c.routeIds.length > 6 && <span className="text-xs text-muted-foreground">+{c.routeIds.length - 6}</span>}</div>
                  <div className="mt-2 font-medium leading-snug">{c.title.ro}</div>
                  <div className="tabular mt-0.5 text-sm text-muted-foreground">până {day(c.window.end)} · {fmt.format(c.departuresLost)} plecări pierdute · {c.stopsSuspended} stații suspendate</div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Suprapuneri cu alte lucrări">
        {!conflicts.data ? <Loading rows={1} /> : pairs.length === 0 ? <p className="text-sm text-muted-foreground">Nicio suprapunere pe aceleași linii sau stații.</p> : (
          <ul className="space-y-3">
            {pairs.map((c) => (
              <li key={c.closureId + c.otherClosureId} className="text-sm">
                <div className="flex items-center gap-2"><Tag tone="closure">Același coridor</Tag><span className="tabular text-muted-foreground">{day(c.overlap.start)} – {day(c.overlap.end)}</span></div>
                <p className="mt-1.5 leading-snug">Cu „{c.otherTitle.ro}”, pe {c.routeIds.length} linii comune.</p>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Linii fără vehicul în datele live" aside={missing.data ? `${hhmm(missing.data.window.start)}–${hhmm(missing.data.window.end)}, ora reală` : undefined}>
        {!missing.data ? <Loading rows={1} /> : noVehicle.length === 0 ? <p className="text-sm text-muted-foreground">Toate liniile din orar au vehicule în datele live.</p> : (
          <ul className="space-y-2">
            {noVehicle.map((r) => (
              <li key={r.routeId} className="flex items-center gap-3">
                <LineBadge routeId={r.routeId} label={r.shortName} size="lg" />
                <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium">{r.longName}</div><div className="tabular text-xs text-muted-foreground">{r.tripsObserved} din {r.tripsInService} curse văzute</div></div>
                <Button size="sm" variant="outline" onClick={() => go("urmaresti")}>Verifică</Button>
              </li>
            ))}
          </ul>
        )}
        <Method>Din datele live ale Primăriei, înregistrate de noi la 15 secunde. Ajunge în CityApp doar după confirmarea unui om.</Method>
      </Section>
    </>
  );
  const map = (
    <MapView closures={(geos.data ?? []).map((c) => ({ id: c.id, geometry: c.geometry }))} onClosure={(id) => go("planifici", id)}
      vehicles={(vehicles.data?.features ?? []).map((v) => ({ id: v.properties.vehicleId, lon: v.geometry.coordinates[0], lat: v.geometry.coordinates[1] }))} />
  );
  return <Split panel={panel} map={map} />;
}

/* ---------------- 2. Planifici ---------------- */
function Question({ g, closureId, onDone }: { g: DecisionGroup; closureId: string; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const answer = async (affected: boolean) => {
    setBusy(true); setErr(null);
    try {
      await app.decideStops(closureId, g.rows.map((r) => ({ ...r, confirmed: affected })));
      setDone(affected ? "Confirmat: nu oprește. Stațiile intră în alertă." : "Confirmat: oprește. Stațiile rămân deservite.");
      onDone();
    } catch (e) { setErr(`Nu s-a salvat (${(e as Error).message}). Încercați din nou.`); } finally { setBusy(false); }
  };
  return (
    <li className="rounded-lg border p-4">
      <p className="font-medium leading-snug">{g.question.ro}</p>
      <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{g.reason.ro}</p>
      {done ? <p className="mt-3 flex items-center gap-1.5 text-sm text-accent-foreground"><Check className="size-4" />{done}</p> : (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" disabled={busy} onClick={() => answer(true)}>Nu oprește{g.suggested === "affected" && " (propunere)"}</Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => answer(false)}>Oprește</Button>
        </div>
      )}
      {err && <p className="mt-2 text-sm text-closure-ink">{err}</p>}
    </li>
  );
}

export function Plan({ closureId }: { closureId: string }) {
  const { closure, analysis, map } = useClosureMap(closureId);
  const impact = useApi(() => app.impact(closureId), undefined, closureId);
  const [all, setAll] = useState(false);
  const [rev, setRev] = useState(0);
  const stops = useMemo(() => {
    const by = new Map<string, AnalysisStop & { lines: string[]; lost: number }>();
    for (const s of analysis.data?.stops ?? []) {
      const x = by.get(s.stopId);
      if (x) { x.lines = uniq([...x.lines, s.routeId]); x.lost += s.departuresLost; if (s.state === "affected") x.state = "affected"; }
      else by.set(s.stopId, { ...s, lines: [s.routeId], lost: s.departuresLost });
    }
    return [...by.values()].sort((a, b) => Number(b.state === "affected") - Number(a.state === "affected") || b.lost - a.lost);
  }, [analysis.data, rev]);
  const t = impact.data?.totals;

  const panel = (
    <>
      <ClosureHead c={closure.data} />
      <div className="grid grid-cols-3 gap-4 px-6 py-5">
        <Figure value={t ? fmt.format(t.departuresLost) : "–"} label="plecări pierdute" tone="closure" kind="estimate" />
        <Figure value={analysis.data ? stops.filter((s) => s.state === "affected").length : "–"} label="stații afectate" />
        <Figure value={analysis.data ? analysis.data.unsureCount : "–"} label="de verificat" />
      </div>
      {t?.residentsLosingStop ? <p className="-mt-1 px-6 pb-4 text-xs text-muted-foreground">{fmt.format(t.residentsLosingStop)} locuitori rămân fără stație la 400 m (model GHSL 2020).</p> : null}
      {(analysis.data?.decisionGroups.length ?? 0) > 0 && (
        <Section title="Întrebări pentru dumneavoastră" aside={`${analysis.data!.decisionGroups.length}`}>
          <ul className="space-y-3">{analysis.data!.decisionGroups.map((g) => <Question key={g.id} g={g} closureId={closureId} onDone={() => setRev((x) => x + 1)} />)}</ul>
        </Section>
      )}
      <Section title="Stațiile" aside={analysis.data ? `${stops.length} în total` : undefined}>
        {!analysis.data ? <Loading /> : (
          <>
            <ul className="divide-y">
              {(all ? stops : stops.slice(0, 10)).map((s) => (
                <li key={s.stopId} className="flex items-start gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2"><span className="truncate font-medium">{s.name}</span>{s.state === "affected" ? <Tag tone="closure">Afectată</Tag> : <Tag>De verificat</Tag>}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-1">{s.lines.map((r) => <LineBadge key={r} routeId={r} />)}</div>
                    {s.nearestServed && <div className="mt-1 text-xs text-muted-foreground">Cea mai apropiată deservită: {s.nearestServed.name}, {fmt.format(Math.round(s.nearestServed.distanceMeters))} m</div>}
                  </div>
                  <div className="tabular text-right text-sm"><div className="font-semibold">{fmt.format(s.lost)}</div><div className="text-xs text-muted-foreground">plecări</div></div>
                </li>
              ))}
            </ul>
            {stops.length > 10 && <Button variant="ghost" className="mt-2 w-full" onClick={() => setAll((x) => !x)}>{all ? "Arată mai puține" : `Arată toate cele ${stops.length}`}</Button>}
          </>
        )}
      </Section>
      <Next to="decizi" label="Alege fereastra" />
    </>
  );
  return <Split panel={panel} map={map} />;
}

/* ---------------- 3. Decizi ---------------- */
export function Decide({ closureId }: { closureId: string }) {
  const { closure, map } = useClosureMap(closureId);
  const w = useApi(() => app.windows(closureId), undefined, closureId);
  const impact = useApi(() => app.impact(closureId), undefined, closureId);
  const [pick, setPick] = useState<number | "notice">("notice");
  const base = w.data?.baselineDeparturesLost;
  const rows = w.data?.candidates ?? [];
  const chosen = pick === "notice" ? base : rows[pick]?.departuresLost;

  const panel = (
    <>
      <ClosureHead c={closure.data} />
      <div className="px-6 pb-6 pt-4">
        <div className="text-sm text-foreground/80">Plecări pierdute în fereastra aleasă</div>
        <div className={cn("tabular mt-1 text-[3.5rem] font-semibold leading-none tracking-tight transition-colors duration-500", pick === "notice" ? "text-closure-ink" : "text-accent-foreground")}>
          {chosen != null ? <Count value={chosen} /> : "–"}
        </div>
        <div className="mt-2 flex min-h-7 flex-wrap items-center gap-2">
          <Kind k="estimate" detail="orar planificat" />
          {base != null && chosen != null && chosen < base && <span className="tabular text-sm font-medium text-accent-foreground">cu {fmt.format(base - chosen)} mai puține decât în anunț</span>}
        </div>
      </div>
      <Section title="Când se face lucrarea">
        {!w.data || !impact.data ? <Loading rows={2} /> : (
          <fieldset>
            <legend className="sr-only">Alegeți fereastra lucrării</legend>
            <ul className="space-y-2">
              <Option checked={pick === "notice"} onChange={() => setPick("notice")} title="Fereastra din anunț"
                when={`${dt(impact.data.window.start)} – ${hhmm(impact.data.window.end)}`} lost={base ?? 0} />
              {rows[0] && <Option checked={pick === 0} onChange={() => setPick(0)} title="Fereastra propusă" tag={<Tag tone="green">Cel mai mic impact</Tag>}
                when={`${dt(rows[0].window.start)} – ${hhmm(rows[0].window.end)}`} lost={rows[0].departuresLost} />}
            </ul>
            {rows.length > 1 && (
              <details className="group mt-3">
                <summary className="cursor-pointer list-none text-sm font-medium text-accent-foreground underline-offset-4 hover:underline">Alte {Math.min(rows.length - 1, 5)} ferestre</summary>
                <ul className="mt-2 space-y-2">
                  {rows.slice(1, 6).map((r, i) => (
                    <Option key={r.window.start} checked={pick === i + 1} onChange={() => setPick(i + 1)} title={`Varianta ${i + 2}`}
                      when={`${dt(r.window.start)} – ${hhmm(r.window.end)}`} lost={r.departuresLost} />
                  ))}
                </ul>
              </details>
            )}
          </fieldset>
        )}
        {w.data && (
          <details className="mt-4 text-sm">
            <summary className="cursor-pointer list-none font-medium text-muted-foreground underline-offset-4 hover:underline">Cum calculăm</summary>
            <Method>{w.data.method.ro}</Method>
          </details>
        )}
      </Section>
      <Next to="publici" label="Continuă spre publicare" />
    </>
  );
  return <Split panel={panel} map={map} />;
}

function Option({ checked, onChange, title, when, lost, tag }: { checked: boolean; onChange: () => void; title: string; when: string; lost: number; tag?: React.ReactNode }) {
  return (
    <li>
      <label className={cn("flex cursor-pointer items-start gap-3 rounded-lg border p-3.5 transition-colors", checked ? "border-primary bg-accent/50 ring-1 ring-primary" : "hover:bg-muted")}>
        <input type="radio" name="window" checked={checked} onChange={onChange} className="mt-1 size-4 accent-[var(--primary)]" />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 font-medium">{title}{tag}</span>
          <span className="tabular block text-sm text-muted-foreground">{when}</span>
        </span>
        <span className="tabular text-right"><span className="block font-semibold">{fmt.format(lost)}</span><span className="text-xs text-muted-foreground">plecări</span></span>
      </label>
    </li>
  );
}

/* ---------------- 4. Publici ---------------- */
export function Publish({ closureId }: { closureId: string }) {
  const { closure, analysis, map } = useClosureMap(closureId);
  const alerts = useApi(app.alerts, undefined, closureId);
  const notices = useApi(() => app.notices(closureId), undefined, closureId);
  const [state, setState] = useState<"idle" | "confirm" | "busy" | "done" | "error">("idle");
  const [err, setErr] = useState("");
  const mine = (alerts.data ?? []).filter((a) => a.closureId === closureId);
  const published = closure.data?.status === "published" || state === "done";
  const posterStops = uniq((analysis.data?.stops ?? []).filter((s) => s.state === "affected").map((s) => s.stopId)).slice(0, 3);
  const stopName = (id: string) => analysis.data?.stops.find((s) => s.stopId === id)?.name ?? id;

  const doPublish = async () => {
    setState("busy");
    try { await app.publish(closureId); setState("done"); } catch (e) { setErr((e as Error).message); setState("error"); }
  };

  const channels: { icon: LucideIcon; name: string; who: string; detail: string; href?: string }[] = [
    { icon: Radio, name: "Alerte GTFS-RT", who: "CityApp, Google Maps, Moovit", detail: published ? `${mine.length} alerte în flux` : "se generează la publicare", href: "/api/feed/alerts.json" },
    { icon: Route, name: "DATEX II", who: "Punctul Național de Acces", detail: "situații de drum, XML", href: "/api/feed/datex.xml" },
    { icon: Network, name: "NGSI-LD", who: "platforma de date a orașului", detail: "entități FIWARE", href: "/api/feed/alerts.ngsi.json" },
    { icon: FileText, name: "Metadate NAP", who: "Punctul Național de Acces", detail: "descrierea fluxurilor", href: "/api/exports/nap-metadata.json" },
    { icon: Megaphone, name: "Anunțuri pe cartiere", who: "site, rețele, avizier", detail: notices.data ? `${notices.data.length} cartiere` : "…" },
  ];

  const panel = (
    <>
      <ClosureHead c={closure.data} />
      <Section title="Ce pleacă și unde">
        <ul className="divide-y">
          {channels.map((c) => (
            <li key={c.name} className="flex items-center gap-3 py-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-muted"><c.icon className="size-4" strokeWidth={1.8} /></span>
              <div className="min-w-0 flex-1"><div className="font-medium">{c.name}</div><div className="text-sm text-muted-foreground">{c.who} · {c.detail}</div></div>
              {c.href && <a href={c.href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm font-medium text-accent-foreground underline-offset-4 hover:underline">Fișier <ExternalLink className="size-3.5" /></a>}
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Afișe A4 pentru stații" aside="cu cod QR și versiune audio">
        {!analysis.data ? <Loading rows={2} /> : (
          <ul className="space-y-2">
            {posterStops.map((id) => (
              <li key={id} className="flex items-center gap-3">
                <QrCode className="size-5 text-muted-foreground" />
                <span className="flex-1 text-sm">{stopName(id)}</span>
                <a href={app.posterUrl(closureId, id)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm font-medium text-accent-foreground underline-offset-4 hover:underline"><Download className="size-3.5" /> PDF</a>
              </li>
            ))}
          </ul>
        )}
      </Section>
      {mine[0] && (
        <Section title="Cum arată alerta">
          <div className="rounded-lg border bg-background p-4">
            <p className="font-medium leading-snug">{mine[0].headerText.ro}</p>
            <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{mine[0].descriptionText.ro}</p>
          </div>
          <Method>Textul exact din fluxul GTFS-RT, așa cum îl primesc CityApp și Google.</Method>
        </Section>
      )}
      {notices.data?.[0] && (
        <Section title="Anunț pentru cartier" aside={notices.data[0].zoneName}>
          <p className="text-sm leading-relaxed">{notices.data[0].body.ro}</p>
        </Section>
      )}
      <div className="sticky bottom-0 border-t bg-card/95 px-6 py-4 backdrop-blur">
        {published ? (
          <p className="flex items-center gap-2 text-[0.95rem] font-medium text-accent-foreground"><Check className="size-4" />Publicată. Fluxurile de mai sus sunt la zi.</p>
        ) : state === "confirm" ? (
          <div className="flex gap-2">
            <Button className="h-11 flex-1 rounded-lg" onClick={doPublish}>Da, publică acum</Button>
            <Button variant="outline" className="h-11 rounded-lg" onClick={() => setState("idle")}><X className="size-4" /> Renunț</Button>
          </div>
        ) : (
          <Button className="h-11 w-full rounded-lg text-[0.95rem]" disabled={state === "busy" || !closure.data} onClick={() => setState("confirm")}>
            {state === "busy" ? "Se publică…" : "Publică lucrarea"}
          </Button>
        )}
        {state === "error" && <div className="mt-2"><Problem>Publicarea nu a reușit: {err}. Nimic nu a plecat; puteți încerca din nou.</Problem></div>}
      </div>
    </>
  );
  return <Split panel={panel} map={map} />;
}

/* ---------------- 5. Urmărești ---------------- */
const MEASURED = "cl_20261102_mocioni";
const minutes = (sec: number) => `${sec < 0 ? "−" : "+"}${fmt.format(Math.abs(Math.round(sec / 6) / 10))} min`;

export function Monitor({ closureId }: { closureId: string }) {
  const missing = useApi(app.missing, 60000);
  const overview = useApi(app.overview);
  const dc = useApi(() => app.detourCost(MEASURED));
  const l23 = overview.data?.missingLines.prepared.rows.find((r) => r.state === "fara_vehicul");
  const vehicles = useApi(api.vehicles, 15000);
  const closure = useApi(() => app.closure(closureId), undefined, closureId);
  const [who, setWho] = useState("Dispecer STPT");
  const [done, setDone] = useState<Record<string, string>>({});
  const rows = (missing.data?.routes ?? []).filter((r) => r.state === "fara_vehicul");

  const triage = async (routeId: string, d: "confirmat" | "respins") => {
    try { await app.triage(routeId, missing.data!.window, d, who); setDone((x) => ({ ...x, [routeId]: d })); }
    catch (e) { setDone((x) => ({ ...x, [routeId]: `eroare: ${(e as Error).message}` })); }
  };

  const prepared = overview.data?.missingLines.prepared;
  const panel = (
    <>
      <Section title={`Linia ${l23?.shortName ?? "23"}, sâmbătă dimineața`} aside={prepared?.case?.label.ro}>
        {!overview.data ? <Loading rows={2} /> : l23 && prepared ? (
          <>
            <div className="flex items-center gap-3">
              <LineBadge routeId={l23.routeId} label={l23.shortName} size="lg" />
              <div className="min-w-0 flex-1"><div className="font-medium leading-snug">{l23.longName}</div>
                <div className="tabular text-sm text-muted-foreground">{hhmm(prepared.window.start)}–{hhmm(prepared.window.end)}</div></div>
              <div className="tabular text-right"><div className="text-2xl font-semibold text-closure-ink">{l23.tripsObserved} din {l23.tripsInService}</div><div className="text-xs text-muted-foreground">curse văzute</div></div>
            </div>
            <p className="mt-4 text-[0.95rem] leading-relaxed">La 10:23, 31 din cele 32 de linii cu curse în orar aveau vehicul în datele live. Linia 23, niciunul.</p>
            <p className="mt-1 text-sm text-muted-foreground">Pentru Primărie și STPT: o listă datată a curselor din orar fără vehicul, pentru verificarea contractului.</p>
            <div className="mt-3"><Kind k="measured" detail="datele live ale Primăriei, înregistrate de noi" /></div>
          </>
        ) : <p className="text-sm text-muted-foreground">Cazul înregistrat nu e disponibil acum.</p>}
      </Section>
      <div className="grid grid-cols-2 gap-4 border-t px-6 py-6">
        <Figure value={vehicles.data ? fmt.format(vehicles.data.features.length) : "–"} label="vehicule în datele live" note="ora reală" />
        <Figure value={missing.data ? rows.length : "–"} label="linii fără vehicul" tone={rows.length ? "closure" : undefined} note={missing.data ? `${hhmm(missing.data.window.start)}–${hhmm(missing.data.window.end)}` : undefined} />
      </div>
      <Section title="Linii din orar fără vehicul în datele live">
        <label className="mb-4 block text-sm">
          <span className="mb-1.5 block font-medium">Cine verifică</span>
          <select value={who} onChange={(e) => setWho(e.target.value)} className="h-10 w-full rounded-md border bg-background px-2.5">
            {["Dispecer STPT", "Biroul de mobilitate, Primărie", "Comunicare STPT"].map((x) => <option key={x}>{x}</option>)}
          </select>
        </label>
        {!missing.data ? <Loading rows={2} /> : rows.length === 0 ? <p className="text-sm text-muted-foreground">Toate liniile din orar au vehicule în datele live acum.</p> : (
          <ul className="space-y-3">
            {rows.map((r) => (
              <li key={r.routeId} className="rounded-lg border p-4">
                <div className="flex items-center gap-3">
                  <LineBadge routeId={r.routeId} label={r.shortName} size="lg" />
                  <div className="min-w-0 flex-1"><div className="font-medium leading-snug">{r.longName}</div>
                    <div className="tabular text-sm text-muted-foreground">{r.tripsObserved} din {r.tripsInService} curse văzute{r.firstMissedTrip ? ` · prima: ${hhmm(r.firstMissedTrip.scheduledTime)}, ${r.firstMissedTrip.stopName}` : ""}</div></div>
                </div>
                {done[r.routeId] ? (
                  <p className="mt-3 flex items-center gap-1.5 text-sm text-accent-foreground"><Check className="size-4" />
                    {done[r.routeId] === "confirmat" ? "Confirmat. Semnalul poate pleca spre CityApp." : done[r.routeId] === "respins" ? "Respins. Nu pleacă nimic." : done[r.routeId]}</p>
                ) : (
                  <div className="mt-3 flex gap-2">
                    <Button size="sm" onClick={() => triage(r.routeId, "confirmat")}>Confirm: nu circulă</Button>
                    <Button size="sm" variant="outline" onClick={() => triage(r.routeId, "respins")}>Circulă, e o lipsă de date</Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        <Method>Comparăm orarul în vigoare cu datele live ale Primăriei, înregistrate de noi la 15 secunde. „Fără vehicul în datele live” nu înseamnă că o cursă nu a avut loc; de aceea confirmă un om.</Method>
      </Section>
      <Section title="Ce au făcut autobuzele pe ocolire" aside="Piața Mocioni">
        {!dc.data ? <Loading rows={2} /> : dc.data.status !== "ok" ? <p className="text-sm text-muted-foreground">Prea puține curse înregistrate încă.</p> : (
          <>
            <div className="grid grid-cols-2 gap-4">
              <Figure value={minutes(dc.data.totals.measuredVsPlanned.sec)} label="față de orar, pe porțiunile noi" note={`${dc.data.totals.measuredVsPlanned.n} de curse`} />
              <Figure value={minutes(dc.data.totals.estimateError.sec)} label="cât a greșit estimarea noastră"
                note={`interval 90 %: ${minutes(dc.data.totals.estimateError.low)} … ${minutes(dc.data.totals.estimateError.high)}`} />
            </div>
            <div className="mt-4"><Kind k="measured" detail={`${dc.data.totals.estimateError.n} de curse, ${dc.data.label.ro}`} /></div>
            <Method>Fără extrapolare la zilele lucrătoare: înregistrarea acoperă vineri după-amiază și sâmbătă.</Method>
          </>
        )}
      </Section>
    </>
  );
  const map = (
    <MapView closures={closure.data ? [{ id: closure.data.id, geometry: closure.data.geometry, selected: true }] : []}
      highlight={rows.map((r) => r.routeId)}
      vehicles={(vehicles.data?.features ?? []).map((v) => ({ id: v.properties.vehicleId, lon: v.geometry.coordinates[0], lat: v.geometry.coordinates[1] }))} />
  );
  return <Split panel={panel} map={map} />;
}

/* ---------------- 6. Raportezi ---------------- */
const OBL = { covered: ["green", "Acoperit"], partial: ["ink", "Parțial"], missing: ["closure", "Lipsește"] } as const;

export function Report() {
  const comp = useApi(app.compliance);
  const ind = useApi(app.indicators);
  const hist = useApi(app.history);
  const exp = useApi(app.exports);
  return (
    <div id="content" className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-8 py-8">
        <h2 className="text-2xl font-semibold tracking-tight">Obligații și ce acoperă exporturile</h2>
        <p className="mt-1 text-muted-foreground">Ce cer actele UE și naționale pentru informarea călătorilor și ce fișier al platformei răspunde.</p>
        <div className="mt-6 overflow-hidden rounded-xl border bg-card">
          {!comp.data ? <div className="p-6"><Loading /></div> : (
            <table className="w-full text-left text-sm">
              <thead className="bg-muted/60 text-muted-foreground"><tr><th className="px-4 py-3 font-medium">Act</th><th className="px-4 py-3 font-medium">Cerința</th><th className="px-4 py-3 font-medium">Termen</th><th className="px-4 py-3 font-medium">Stare</th></tr></thead>
              <tbody className="divide-y">
                {comp.data.obligations.map((o) => {
                  const [tone, label] = OBL[o.status as keyof typeof OBL] ?? ["neutral", o.status];
                  return (
                    <tr key={o.id} className="align-top">
                      <td className="px-4 py-3 font-medium">{o.act}</td>
                      <td className="px-4 py-3"><div>{o.requirement.ro}</div>{o.note?.ro && <div className="mt-1 text-xs text-muted-foreground">{o.note.ro}</div>}</td>
                      <td className="tabular px-4 py-3 text-muted-foreground">{o.deadline}</td>
                      <td className="px-4 py-3"><Tag tone={tone as "green"}>{label}</Tag></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <h2 className="mt-12 text-2xl font-semibold tracking-tight">Lucrările de până acum</h2>
        <p className="mt-1 text-muted-foreground">Cu câte ore înainte a anunțat STPT fiecare lucrare și ce a pierdut orarul.</p>
        <div className="mt-6 overflow-hidden rounded-xl border bg-card">
          {!hist.data ? <div className="p-6"><Loading /></div> : (
            <table className="w-full text-left text-sm">
              <thead className="bg-muted/60 text-muted-foreground"><tr><th className="px-4 py-3 font-medium">Lucrarea</th><th className="px-4 py-3 font-medium">Început</th><th className="px-4 py-3 text-right font-medium">Anunț înainte</th><th className="px-4 py-3 text-right font-medium">Plecări pierdute</th></tr></thead>
              <tbody className="divide-y">
                {hist.data.map((h) => (
                  <tr key={h.closureId}>
                    <td className="px-4 py-3"><a href={h.sourceUrl} target="_blank" rel="noreferrer" className="font-medium underline-offset-4 hover:underline">{h.title.ro}</a></td>
                    <td className="tabular px-4 py-3 text-muted-foreground">{day(h.window.start)}</td>
                    <td className="tabular px-4 py-3 text-right">{h.leadHours != null ? `${fmt.format(Math.round(h.leadHours))} h` : "–"}</td>
                    <td className="tabular px-4 py-3 text-right">{fmt.format(h.departuresLost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">Reconstituit din anunțurile STPT; plecările pierdute sunt o estimare pe orarul planificat.</p>

        <div className="mt-12 grid grid-cols-1 gap-10 md:grid-cols-2">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">Indicatori</h2>
            {!ind.data ? <div className="mt-4"><Loading /></div> : (
              <dl className="mt-4 divide-y rounded-xl border bg-card">
                {ind.data.indicators.map((i) => (
                  <div key={i.code} className="flex items-baseline justify-between gap-4 px-4 py-3 text-sm">
                    <dt>{i.name.ro}</dt><dd className="tabular whitespace-nowrap font-semibold">{fmt.format(Math.round(i.value * 10) / 10)} {i.unit}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
          <div>
            <h2 className="text-xl font-semibold tracking-tight">Fișiere publice</h2>
            {!exp.data ? <div className="mt-4"><Loading /></div> : (
              <ul className="mt-4 divide-y rounded-xl border bg-card">
                {exp.data.map((x) => (
                  <li key={x.name} className="flex items-center justify-between gap-4 px-4 py-3 text-sm">
                    <span><span className="font-medium">{x.format}</span><span className="block text-xs text-muted-foreground">{x.standard}</span></span>
                    <a href={x.url} target="_blank" rel="noreferrer" className="inline-flex shrink-0 items-center gap-1 font-medium text-accent-foreground underline-offset-4 hover:underline">{x.name} <ExternalLink className="size-3.5" /></a>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
