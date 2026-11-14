import { useMemo, useState, type ReactNode } from "react";
import { ArrowRight, Check, Download, ExternalLink, FileText, Megaphone, Network, QrCode, Radio, Route, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LineBadge } from "@/landing/LineBadge";
import { api, fmt, hhmm, useApi, type Vehicle } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { FeatureCollection, Point } from "geojson";
import { app, day, dt, type AnalysisStop, type DecisionGroup } from "./data";
import type { MapStop } from "./MapView";
import { go, type StepId } from "./router";
import { Answer, Count, Fold, Folds, Kind, Loading, Method, Problem, Stat, Step, Tag, useMapLayers, type Layers } from "./ui";

const uniq = <T,>(xs: T[]) => [...new Set(xs)];
const pl = (n: number, one: string, many: string) => `${fmt.format(n)} ${n === 1 ? one : many}`;
const toVehicles = (d: FeatureCollection<Point, Vehicle> | null) =>
  (d?.features ?? []).map((v) => ({ id: v.properties.vehicleId, lon: v.geometry.coordinates[0], lat: v.geometry.coordinates[1] }));

function Next({ to, children }: { to: StepId; children: ReactNode }) {
  return <Button className="h-11 w-full rounded-xl text-[0.95rem]" onClick={() => go(to)}>{children} <ArrowRight className="size-4" /></Button>;
}

function Live({ d }: { d: FeatureCollection<Point, Vehicle> | null }) {
  const at = d?.features[0]?.properties.updatedAt;
  return (
    <p className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
      <span className="relative flex size-2" aria-hidden>
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary/50" />
        <span className="relative inline-flex size-2 rounded-full bg-primary" />
      </span>
      <span className="tabular">{d ? `${fmt.format(d.features.length)} de vehicule în datele live${at ? `, ${hhmm(at)}` : ""}` : "Se citesc vehiculele…"}</span>
    </p>
  );
}

/* ---------- one closure on the map: the work, its lines in colour, its stops ---------- */
function useClosure(closureId: string) {
  const closure = useApi(() => app.closure(closureId), undefined, closureId);
  const analysis = useApi(() => app.analysis(closureId), undefined, closureId);
  const mapStops: MapStop[] = useMemo(() => {
    const seen = new Set<string>();
    return (analysis.data?.stops ?? []).filter((s) => !seen.has(s.stopId) && seen.add(s.stopId))
      .map((s) => ({ id: s.stopId, name: s.name, lon: s.location[0], lat: s.location[1], tone: s.state === "affected" ? "closed" : "unsure" }));
  }, [analysis.data]);
  const layers = useMemo<Layers>(() => ({
    closures: closure.data ? [{ id: closure.data.id, geometry: closure.data.geometry, selected: true }] : [],
    highlight: closure.data?.routeIds ?? [], stops: mapStops, fitTo: closure.data ? closureId : undefined,
  }), [closure.data, mapStops, closureId]);
  useMapLayers(layers);
  return { closure, analysis };
}

/* ---------------- 1. Ansamblu ---------------- */
export function Overview() {
  const o = useApi(app.overview);
  const missing = useApi(app.missing, 60000);
  const vehicles = useApi(api.vehicles, 15000);
  const [hover, setHover] = useState<string | null>(null);
  const active = o.data?.activeClosures ?? [];
  const ids = active.map((c) => c.id);
  const geos = useApi(() => (ids.length ? Promise.all(ids.map((id) => app.closure(id))) : Promise.resolve(null)), undefined, ids.join());
  const conflicts = useApi(() => (ids.length ? Promise.all(ids.map((id) => app.conflicts(id))).then((xs) => xs.flat()) : Promise.resolve(null)), undefined, ids.join());
  const pairs = uniq((conflicts.data ?? []).map((c) => [c.closureId, c.otherClosureId].sort().join("|")))
    .map((k) => conflicts.data!.find((c) => [c.closureId, c.otherClosureId].sort().join("|") === k)!);
  const noVehicle = (missing.data?.routes ?? []).filter((r) => r.state === "fara_vehicul");

  const vs = useMemo(() => toVehicles(vehicles.data), [vehicles.data]);
  const layers = useMemo<Layers>(() => ({
    fitTo: "city", vehicles: vs,
    closures: (geos.data ?? []).map((c) => ({ id: c.id, geometry: c.geometry, selected: c.id === hover })),
  }), [geos.data, vs, hover]);
  useMapLayers(layers);

  return (
    <Step title="Ce e închis acum"
      answer={<Answer value={o.data ? active.length : "–"} label={active.length === 1 ? "lucrare activă pe rețea" : "lucrări active pe rețea"}><Live d={vehicles.data} /></Answer>}>
      {o.error ? <div className="mt-6"><Problem>Lucrările nu s-au încărcat ({o.error}). Reîncărcați pagina.</Problem></div> : !o.data ? <div className="mt-6"><Loading rows={2} /></div> : (
        <ul className="-mx-3 mt-6 space-y-1">
          {active.map((c) => (
            <li key={c.id}>
              <button type="button" onClick={() => go("planifici", c.id)} onPointerEnter={() => setHover(c.id)} onPointerLeave={() => setHover(null)}
                onFocus={() => setHover(c.id)} onBlur={() => setHover(null)}
                className="group flex w-full items-start gap-3 rounded-xl px-3 py-3 text-left transition-colors hover:bg-muted">
                <span className="mt-1.5 size-2.5 shrink-0 rounded-full bg-closure" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block font-medium leading-snug">{c.title.ro}</span>
                  <span className="tabular mt-1 block text-sm text-muted-foreground">până {day(c.window.end)} · {pl(c.routeIds.length, "linie", "linii")} · {pl(c.stopsSuspended, "stație suspendată", "stații suspendate")}</span>
                </span>
                <ArrowRight className="mt-1 size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <Folds>
        <Fold id="overlaps" title="Suprapuneri între lucrări" aside={conflicts.data ? pairs.length : "…"}>
          {pairs.length === 0 ? <p className="text-muted-foreground">Nicio suprapunere pe aceleași linii sau stații.</p> : (
            <ul className="space-y-3">
              {pairs.map((c) => (
                <li key={c.closureId + c.otherClosureId} className="leading-snug">
                  <span className="tabular text-muted-foreground">{day(c.overlap.start)} – {day(c.overlap.end)} · </span>
                  cu „{c.otherTitle.ro}”, pe {c.routeIds.length} linii comune
                </li>
              ))}
            </ul>
          )}
        </Fold>
        <Fold id="novehicle" title="Linii fără vehicul în datele live" aside={missing.data ? noVehicle.length : "…"}>
          {noVehicle.length === 0 ? <p className="text-muted-foreground">Toate liniile din orar au vehicule în datele live.</p> : (
            <ul className="space-y-2">
              {noVehicle.map((r) => (
                <li key={r.routeId} className="flex items-center gap-3">
                  <LineBadge routeId={r.routeId} label={r.shortName} size="lg" />
                  <span className="min-w-0 flex-1"><span className="block truncate font-medium">{r.longName}</span>
                    <span className="tabular text-xs text-muted-foreground">{r.tripsObserved} din {r.tripsInService} curse văzute</span></span>
                  <Button size="sm" variant="outline" onClick={() => go("urmaresti")}>Verifică</Button>
                </li>
              ))}
            </ul>
          )}
          <Method>Din datele live ale Primăriei, înregistrate de noi la 15 secunde. Ajunge în CityApp doar după confirmarea unui om.</Method>
        </Fold>
      </Folds>
    </Step>
  );
}

/* ---------------- 2. Planifici ---------------- */
function Question({ g, closureId, onDone }: { g: DecisionGroup; closureId: string; onDone: (label: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const answer = async (affected: boolean) => {
    setBusy(true); setErr(null);
    try {
      await app.decideStops(closureId, g.rows.map((r) => ({ ...r, confirmed: affected })));
      const label = affected ? "Nu oprește. Stațiile intră în alertă." : "Oprește. Stațiile rămân deservite.";
      setDone(label); onDone(label);
    } catch (e) { setErr(`Nu s-a salvat (${(e as Error).message}). Încercați din nou.`); } finally { setBusy(false); }
  };
  return (
    <motion.li layout transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
      className={cn("rounded-xl border p-4 transition-colors", done && "border-transparent bg-accent/60")}>
      <p className="font-medium leading-snug">{g.question.ro}</p>
      {done ? (
        <p className="mt-2 flex items-center gap-1.5 text-sm font-medium text-accent-foreground"><Check className="size-4" />{done}</p>
      ) : (
        <>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Button disabled={busy} onClick={() => answer(true)} className="rounded-lg">Nu oprește</Button>
            <Button disabled={busy} variant="outline" onClick={() => answer(false)} className="rounded-lg">Oprește</Button>
          </div>
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer list-none text-muted-foreground underline-offset-4 hover:underline">
              De ce întrebăm{g.suggested === "affected" ? " · propunerea noastră: nu oprește" : ""}
            </summary>
            <p className="mt-1.5 leading-relaxed text-muted-foreground">{g.reason.ro}</p>
          </details>
        </>
      )}
      {err && <p className="mt-2 text-sm text-closure-ink">{err}</p>}
    </motion.li>
  );
}

export function Plan({ closureId }: { closureId: string }) {
  const { closure, analysis } = useClosure(closureId);
  const impact = useApi(() => app.impact(closureId), undefined, closureId);
  const [answered, setAnswered] = useState(0);
  const stops = useMemo(() => {
    const by = new Map<string, AnalysisStop & { lines: string[]; lost: number }>();
    for (const s of analysis.data?.stops ?? []) {
      const x = by.get(s.stopId);
      if (x) { x.lines = uniq([...x.lines, s.routeId]); x.lost += s.departuresLost; if (s.state === "affected") x.state = "affected"; }
      else by.set(s.stopId, { ...s, lines: [s.routeId], lost: s.departuresLost });
    }
    return [...by.values()].sort((a, b) => Number(b.state === "affected") - Number(a.state === "affected") || b.lost - a.lost);
  }, [analysis.data]);
  const t = impact.data?.totals;
  const groups = analysis.data?.decisionGroups ?? [];
  const affected = stops.filter((s) => s.state === "affected").length;

  return (
    <Step title="Cine pierde serviciul"
      answer={
        <Answer value={analysis.data ? affected : "–"} label="stații afectate de lucrare">
          <div className="mt-3 flex flex-wrap gap-1.5">{(closure.data?.routeIds ?? []).map((r) => <LineBadge key={r} routeId={r} />)}</div>
          <div className="mt-6 grid grid-cols-2 gap-5">
            <Stat value={t ? fmt.format(t.departuresLost) : "–"} label="plecări pierdute" kind="estimate" />
            {t?.residentsLosingStop ? <Stat value={fmt.format(t.residentsLosingStop)} label="locuitori fără stație la 400 m, model GHSL" kind="estimate" /> : null}
          </div>
        </Answer>
      }
      footer={<Next to="decizi">Alege când se face lucrarea</Next>}>
      {groups.length > 0 && (
        <section className="mt-8">
          <div className="flex items-baseline justify-between">
            <h3 className="font-semibold">De hotărât</h3>
            <span className="tabular text-sm text-muted-foreground">{Math.min(answered, groups.length)} din {groups.length}</span>
          </div>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-muted">
            <motion.div className="h-full rounded-full bg-primary" initial={false} animate={{ width: `${(Math.min(answered, groups.length) / groups.length) * 100}%` }} transition={{ duration: 0.3, ease: "easeOut" }} />
          </div>
          <ul className="mt-4 space-y-3">{groups.map((g) => <Question key={g.id} g={g} closureId={closureId} onDone={() => setAnswered((x) => x + 1)} />)}</ul>
        </section>
      )}
      <Folds>
        <Fold id="stops" title="Toate stațiile" aside={analysis.data ? stops.length : "…"}>
          <ul className="divide-y">
            {stops.map((s) => (
              <li key={s.stopId} className="flex items-start gap-3 py-3">
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2"><span className="truncate font-medium">{s.name}</span>{s.state === "affected" ? <Tag tone="closure">Afectată</Tag> : <Tag>De verificat</Tag>}</span>
                  <span className="mt-1 flex flex-wrap items-center gap-1">{s.lines.map((r) => <LineBadge key={r} routeId={r} />)}</span>
                  {s.nearestServed && <span className="mt-1 block text-xs text-muted-foreground">Cea mai apropiată deservită: {s.nearestServed.name}, {fmt.format(Math.round(s.nearestServed.distanceMeters))} m</span>}
                </span>
                <span className="tabular text-right text-sm"><span className="block font-semibold">{fmt.format(s.lost)}</span><span className="text-xs text-muted-foreground">plecări</span></span>
              </li>
            ))}
          </ul>
        </Fold>
      </Folds>
    </Step>
  );
}

/* ---------------- 3. Decizi ---------------- */
function WindowOption({ value, title, when, lost, tag }: { value: string; title: string; when: string; lost: number; tag?: ReactNode }) {
  return (
    <label className="flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition-colors hover:bg-muted/60 has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-accent/50">
      <RadioGroupItem value={value} className="mt-0.5" />
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2 font-medium">{title}{tag}</span>
        <span className="tabular block text-sm text-muted-foreground">{when}</span>
      </span>
      <span className="tabular text-right"><span className="block font-semibold">{fmt.format(lost)}</span><span className="text-xs text-muted-foreground">plecări</span></span>
    </label>
  );
}

export function Decide({ closureId }: { closureId: string }) {
  useClosure(closureId);
  const w = useApi(() => app.windows(closureId), undefined, closureId);
  const impact = useApi(() => app.impact(closureId), undefined, closureId);
  const [pick, setPick] = useState("notice");
  const base = w.data?.baselineDeparturesLost;
  const rows = w.data?.candidates ?? [];
  const chosen = pick === "notice" ? base : rows[Number(pick)]?.departuresLost;

  return (
    <Step title="Când se face lucrarea"
      answer={
        <Answer value={chosen != null ? <Count value={chosen} /> : "–"} tone={pick === "notice" ? "closure" : "green"} label="plecări pierdute în fereastra aleasă"
          kind={<div className="flex min-h-7 flex-wrap items-center gap-2"><Kind k="estimate" detail="orar planificat" />
            {base != null && chosen != null && chosen < base && <span className="tabular text-sm font-medium text-accent-foreground">cu {fmt.format(base - chosen)} mai puține decât în anunț</span>}</div>} />
      }
      footer={<Next to="publici">Pregătește anunțul</Next>}>
      {!w.data || !impact.data ? <div className="mt-7"><Loading rows={2} /></div> : (
        <RadioGroup value={pick} onValueChange={setPick} aria-label="Fereastra lucrării" className="mt-7 block">
          <div className="space-y-2.5">
            <WindowOption value="notice" title="Fereastra din anunț" when={`${dt(impact.data.window.start)} – ${hhmm(impact.data.window.end)}`} lost={base ?? 0} />
            {rows[0] && <WindowOption value="0" title="Fereastra propusă" tag={<Tag tone="green">Cel mai mic impact</Tag>}
              when={`${dt(rows[0].window.start)} – ${hhmm(rows[0].window.end)}`} lost={rows[0].departuresLost} />}
          </div>
          <Folds>
            {rows.length > 1 && (
              <Fold id="more" title="Alte ferestre" aside={Math.min(rows.length - 1, 5)}>
                <div className="space-y-2.5">
                  {rows.slice(1, 6).map((r, i) => (
                    <WindowOption key={r.window.start} value={String(i + 1)} title={`Varianta ${i + 2}`} when={`${dt(r.window.start)} – ${hhmm(r.window.end)}`} lost={r.departuresLost} />
                  ))}
                </div>
              </Fold>
            )}
            <Fold id="method" title="Cum calculăm"><p className="leading-relaxed text-muted-foreground">{w.data.method.ro}</p></Fold>
          </Folds>
        </RadioGroup>
      )}
    </Step>
  );
}

/* ---------------- 4. Publici ---------------- */
export function Publish({ closureId }: { closureId: string }) {
  const { closure, analysis } = useClosure(closureId);
  const alerts = useApi(app.alerts, undefined, closureId);
  const notices = useApi(() => app.notices(closureId), undefined, closureId);
  const [state, setState] = useState<"idle" | "confirm" | "busy" | "done" | "error">("idle");
  const [err, setErr] = useState("");
  const mine = (alerts.data ?? []).filter((a) => a.closureId === closureId);
  const published = closure.data?.status === "published" || state === "done";
  const posterStops = uniq((analysis.data?.stops ?? []).filter((s) => s.state === "affected").map((s) => s.stopId)).slice(0, 3);
  const stopName = (id: string) => analysis.data?.stops.find((s) => s.stopId === id)?.name ?? id;
  const notice = notices.data?.[0];

  const doPublish = async () => {
    setState("busy");
    try { await app.publish(closureId); setState("done"); } catch (e) { setErr((e as Error).message); setState("error"); }
  };

  const channels: { icon: LucideIcon; name: string; who: string; href?: string }[] = [
    { icon: Radio, name: "Alerte GTFS-RT", who: "CityApp, Google Maps, Moovit", href: "/api/feed/alerts.json" },
    { icon: Route, name: "DATEX II", who: "Punctul Național de Acces", href: "/api/feed/datex.xml" },
    { icon: Network, name: "NGSI-LD", who: "platforma de date a orașului", href: "/api/feed/alerts.ngsi.json" },
    { icon: FileText, name: "Metadate NAP", who: "Punctul Național de Acces", href: "/api/exports/nap-metadata.json" },
    { icon: Megaphone, name: "Anunțuri pe cartiere", who: notices.data ? `site, rețele, avizier · ${notices.data.length} cartiere` : "site, rețele, avizier" },
  ];

  const preview = mine[0]
    ? { icon: Radio, from: "Alertă GTFS-RT · CityApp, Google Maps", head: mine[0].headerText.ro, body: mine[0].descriptionText.ro,
        note: "Textul exact din fluxul GTFS-RT, așa cum îl primesc CityApp și Google." }
    : notice ? { icon: Megaphone, from: `Anunț pentru cartierul ${notice.zoneName}`, head: notice.title.ro, body: notice.body.ro,
        note: "Anunțul generat pentru cartier. Alerta pentru aplicații pleacă la publicare." } : null;

  return (
    <Step title="Ce află călătorii"
      answer={
        <div className="mt-5">
          {!preview ? <Loading rows={2} /> : (
            <div className="rounded-2xl bg-muted/70 p-4">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className="grid size-6 place-items-center rounded-md bg-closure text-white"><preview.icon className="size-3.5" /></span>{preview.from}
              </div>
              <p className="mt-2.5 font-semibold leading-snug">{preview.head}</p>
              <p className="mt-1 line-clamp-6 text-sm leading-relaxed text-foreground/80">{preview.body}</p>
            </div>
          )}
          {preview && <p className="mt-2 text-xs text-muted-foreground">{preview.note}</p>}
        </div>
      }
      footer={
        <div>
          {published ? (
            <p className="flex h-11 items-center gap-2 text-[0.95rem] font-medium text-accent-foreground"><Check className="size-4" />Publicată. Fluxurile sunt la zi.</p>
          ) : state === "confirm" ? (
            <div className="flex gap-2">
              <Button className="h-11 flex-1 rounded-xl" onClick={doPublish}>Da, publică acum</Button>
              <Button variant="outline" className="h-11 rounded-xl" onClick={() => setState("idle")}><X className="size-4" /> Renunț</Button>
            </div>
          ) : (
            <Button className="h-11 w-full rounded-xl text-[0.95rem]" disabled={state === "busy" || !closure.data} onClick={() => setState("confirm")}>
              {state === "busy" ? "Se publică…" : "Publică lucrarea"}
            </Button>
          )}
          {state === "error" && <div className="mt-2"><Problem>Publicarea nu a reușit: {err}. Nimic nu a plecat; puteți încerca din nou.</Problem></div>}
        </div>
      }>
      <Folds>
        <Fold id="channels" title="Unde pleacă" aside={`${channels.length} canale`}>
          <ul className="divide-y">
            {channels.map((c) => (
              <li key={c.name} className="flex items-center gap-3 py-3">
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-muted"><c.icon className="size-4" strokeWidth={1.8} /></span>
                <span className="min-w-0 flex-1"><span className="block font-medium">{c.name}</span><span className="block text-muted-foreground">{c.who}</span></span>
                {c.href && <a href={c.href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-accent-foreground underline-offset-4 hover:underline">Fișier <ExternalLink className="size-3.5" /></a>}
              </li>
            ))}
          </ul>
        </Fold>
        <Fold id="posters" title="Afișe pentru stații" aside={analysis.data ? `${posterStops.length} PDF` : "…"}>
          <ul className="space-y-2.5">
            {posterStops.map((id) => (
              <li key={id} className="flex items-center gap-3">
                <QrCode className="size-5 text-muted-foreground" />
                <span className="flex-1">{stopName(id)}</span>
                <a href={app.posterUrl(closureId, id)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-accent-foreground underline-offset-4 hover:underline"><Download className="size-3.5" /> PDF</a>
              </li>
            ))}
          </ul>
          <Method>A4, cu cod QR spre pagina stației și versiune audio.</Method>
        </Fold>
      </Folds>
    </Step>
  );
}

/* ---------------- 5. Urmărești ---------------- */
const MEASURED = "cl_20261102_mocioni";
const minutes = (sec: number) => `${sec < 0 ? "−" : "+"}${fmt.format(Math.abs(Math.round(sec / 6) / 10))} min`;
const ROLES = ["Dispecer STPT", "Biroul de mobilitate, Primărie", "Comunicare STPT"];

export function Monitor({ closureId }: { closureId: string }) {
  const missing = useApi(app.missing, 60000);
  const overview = useApi(app.overview);
  const dc = useApi(() => app.detourCost(MEASURED));
  const vehicles = useApi(api.vehicles, 15000);
  const closure = useApi(() => app.closure(closureId), undefined, closureId);
  const [who, setWho] = useState(ROLES[0]);
  const [done, setDone] = useState<Record<string, string>>({});
  const rows = (missing.data?.routes ?? []).filter((r) => r.state === "fara_vehicul");
  const prepared = overview.data?.missingLines.prepared;
  const l23 = prepared?.rows.find((r) => r.state === "fara_vehicul");

  const vs = useMemo(() => toVehicles(vehicles.data), [vehicles.data]);
  const rowIds = rows.map((r) => r.routeId).join();
  const layers = useMemo<Layers>(() => ({
    fitTo: "city", vehicles: vs, highlight: rowIds ? rowIds.split(",") : [],
    closures: closure.data ? [{ id: closure.data.id, geometry: closure.data.geometry, selected: true }] : [],
  }), [vs, rowIds, closure.data]);
  useMapLayers(layers);

  const triage = async (routeId: string, d: "confirmat" | "respins") => {
    try { await app.triage(routeId, missing.data!.window, d, who); setDone((x) => ({ ...x, [routeId]: d })); }
    catch (e) { setDone((x) => ({ ...x, [routeId]: `eroare: ${(e as Error).message}` })); }
  };

  return (
    <Step title="Ce au făcut vehiculele"
      answer={!overview.data ? <div className="mt-5"><Loading rows={2} /></div> : l23 && prepared ? (
        <Answer value={`${l23.tripsObserved} din ${l23.tripsInService}`} tone="closure"
          label={<span className="flex flex-wrap items-center gap-x-2 gap-y-1">curse văzute pe linia <LineBadge routeId={l23.routeId} label={l23.shortName} /> sâmbătă, {hhmm(prepared.window.start)}–{hhmm(prepared.window.end)}</span>}
          kind={<Kind k="measured" detail="datele live ale Primăriei" />}>
          <p className="mt-4 text-[0.95rem] leading-relaxed">La 10:23, 31 din cele 32 de linii cu curse în orar aveau vehicul în datele live. Linia 23, niciunul.</p>
        </Answer>
      ) : <p className="mt-5 text-sm text-muted-foreground">Cazul înregistrat nu e disponibil acum.</p>}
      footer={<Next to="raportezi">Vezi ce raportăm</Next>}>
      <section className="mt-8">
        <div className="flex items-baseline justify-between gap-3">
          <h3 className="font-semibold">De confirmat acum</h3>
          {missing.data && <span className="tabular text-sm text-muted-foreground">{hhmm(missing.data.window.start)}–{hhmm(missing.data.window.end)}</span>}
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Confirm ca</span>
          <select value={who} onChange={(e) => setWho(e.target.value)} className="h-9 min-w-0 flex-1 rounded-lg border bg-background px-2.5 font-medium">
            {ROLES.map((x) => <option key={x}>{x}</option>)}
          </select>
        </label>
        {!missing.data ? <div className="mt-4"><Loading rows={2} /></div> : rows.length === 0 ? <p className="mt-4 text-sm text-muted-foreground">Toate liniile din orar au vehicule în datele live acum.</p> : (
          <ul className="mt-4 space-y-3">
            {rows.map((r) => (
              <motion.li layout key={r.routeId} className={cn("rounded-xl border p-4", done[r.routeId] && "border-transparent bg-accent/60")}>
                <div className="flex items-center gap-3">
                  <LineBadge routeId={r.routeId} label={r.shortName} size="lg" />
                  <span className="min-w-0 flex-1"><span className="block font-medium leading-snug">{r.longName}</span>
                    <span className="tabular block text-sm text-muted-foreground">{r.tripsObserved} din {r.tripsInService} curse văzute{r.firstMissedTrip ? ` · prima la ${hhmm(r.firstMissedTrip.scheduledTime)}` : ""}</span></span>
                </div>
                {done[r.routeId] ? (
                  <p className="mt-3 flex items-center gap-1.5 text-sm font-medium text-accent-foreground"><Check className="size-4" />
                    {done[r.routeId] === "confirmat" ? "Confirmat. Semnalul poate pleca spre CityApp." : done[r.routeId] === "respins" ? "Respins. Nu pleacă nimic." : done[r.routeId]}</p>
                ) : (
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <Button size="sm" className="rounded-lg" onClick={() => triage(r.routeId, "confirmat")}>Nu circulă</Button>
                    <Button size="sm" variant="outline" className="rounded-lg" onClick={() => triage(r.routeId, "respins")}>Circulă, lipsesc date</Button>
                  </div>
                )}
              </motion.li>
            ))}
          </ul>
        )}
        <Method>„Fără vehicul în datele live” nu înseamnă că o cursă nu a avut loc; de aceea confirmă un om.</Method>
      </section>
      <Folds>
        <Fold id="mocioni" title="Ocolirea de la Piața Mocioni" aside="măsurat">
          {!dc.data ? <Loading rows={2} /> : dc.data.status !== "ok" ? <p className="text-muted-foreground">Prea puține curse înregistrate încă.</p> : (
            <>
              <div className="grid grid-cols-2 gap-5">
                <Stat value={minutes(dc.data.totals.measuredVsPlanned.sec)} label={`față de orar, pe porțiunile noi (${dc.data.totals.measuredVsPlanned.n} curse)`} />
                <Stat value={minutes(dc.data.totals.estimateError.sec)} label={`cât a greșit estimarea noastră (90 %: ${minutes(dc.data.totals.estimateError.low)} … ${minutes(dc.data.totals.estimateError.high)})`} />
              </div>
              <div className="mt-4"><Kind k="measured" detail={`${dc.data.totals.estimateError.n} curse, ${dc.data.label.ro}`} /></div>
              <Method>Fără extrapolare la zilele lucrătoare: înregistrarea acoperă vineri după-amiază și sâmbătă.</Method>
            </>
          )}
        </Fold>
      </Folds>
    </Step>
  );
}

/* ---------------- 6. Raportezi ---------------- */
const OBL = { covered: ["green", "Acoperit"], partial: ["ink", "Parțial"], missing: ["closure", "Lipsește"] } as const;
const TH = "px-4 py-3 font-medium";

export function Report() {
  const comp = useApi(app.compliance);
  const ind = useApi(app.indicators);
  const hist = useApi(app.history);
  const exp = useApi(app.exports);
  const by = (s: string) => comp.data?.obligations.filter((o) => o.status === s).length ?? 0;

  return (
    <Step title="Ce raportăm" inner="mx-auto w-full max-w-5xl pb-24"
      answer={
        <Answer value={comp.data ? comp.data.obligations.length : "–"} label="obligații UE și naționale de informare a călătorilor, cu ce fișier al platformei răspunde fiecăreia">
          {comp.data && <div className="mt-4 flex flex-wrap gap-2"><Tag tone="green">{pl(by("covered"), "acoperită", "acoperite")}</Tag><Tag tone="ink">{by("partial")} parțial</Tag><Tag tone="closure">{pl(by("missing"), "lipsește", "lipsesc")}</Tag></div>}
        </Answer>
      }>
      <Tabs defaultValue="obl" className="mt-8">
        <TabsList>
          <TabsTrigger value="obl">Obligații</TabsTrigger>
          <TabsTrigger value="hist">Lucrări anterioare</TabsTrigger>
          <TabsTrigger value="ind">Indicatori</TabsTrigger>
          <TabsTrigger value="files">Fișiere publice</TabsTrigger>
        </TabsList>
        <TabsContent value="obl" className="mt-4">
          {!comp.data ? <Loading /> : (
            <div className="overflow-hidden rounded-xl border">
              <table className="w-full text-left text-sm">
                <thead className="bg-muted/60 text-muted-foreground"><tr><th className={TH}>Act</th><th className={TH}>Cerința</th><th className={TH}>Termen</th><th className={TH}>Stare</th></tr></thead>
                <tbody className="divide-y">
                  {comp.data.obligations.map((o) => {
                    const [tone, label] = OBL[o.status as keyof typeof OBL] ?? ["neutral", o.status];
                    return (
                      <tr key={o.id} className="align-top">
                        <td className="px-4 py-3 font-medium">{o.act}</td>
                        <td className="px-4 py-3"><div>{o.requirement.ro}</div>{o.note?.ro && <div className="mt-1 text-xs text-muted-foreground">{o.note.ro}</div>}</td>
                        <td className="tabular whitespace-nowrap px-4 py-3 text-muted-foreground">{o.deadline}</td>
                        <td className="px-4 py-3"><Tag tone={tone as "green"}>{label}</Tag></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </TabsContent>
        <TabsContent value="hist" className="mt-4">
          {!hist.data ? <Loading /> : (
            <div className="overflow-hidden rounded-xl border">
              <table className="w-full text-left text-sm">
                <thead className="bg-muted/60 text-muted-foreground"><tr><th className={TH}>Lucrarea</th><th className={TH}>Început</th><th className={`${TH} text-right`}>Anunț înainte</th><th className={`${TH} text-right`}>Plecări pierdute</th></tr></thead>
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
            </div>
          )}
          <Method>Reconstituit din anunțurile STPT; plecările pierdute sunt o estimare pe orarul planificat.</Method>
        </TabsContent>
        <TabsContent value="ind" className="mt-4">
          {!ind.data ? <Loading /> : (
            <dl className="divide-y rounded-xl border">
              {ind.data.indicators.map((i) => (
                <div key={i.code} className="flex items-baseline justify-between gap-4 px-4 py-3 text-sm">
                  <dt>{i.name.ro}</dt><dd className="tabular whitespace-nowrap font-semibold">{fmt.format(Math.round(i.value * 10) / 10)} {i.unit}</dd>
                </div>
              ))}
            </dl>
          )}
        </TabsContent>
        <TabsContent value="files" className="mt-4">
          {!exp.data ? <Loading /> : (
            <ul className="divide-y rounded-xl border">
              {exp.data.map((x) => (
                <li key={x.name} className="flex items-center justify-between gap-4 px-4 py-3 text-sm">
                  <span><span className="font-medium">{x.format}</span><span className="block text-xs text-muted-foreground">{x.standard}</span></span>
                  <a href={x.url} target="_blank" rel="noreferrer" className="inline-flex shrink-0 items-center gap-1 font-medium text-accent-foreground underline-offset-4 hover:underline">{x.name} <ExternalLink className="size-3.5" /></a>
                </li>
              ))}
            </ul>
          )}
        </TabsContent>
      </Tabs>
    </Step>
  );
}
