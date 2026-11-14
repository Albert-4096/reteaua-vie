import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import type { Position } from "geojson";
import { Button } from "@/components/ui/button";
import { LineBadge } from "@/landing/LineBadge";
import { useNetwork } from "@/lib/network";
import { cn } from "@/lib/utils";
import { app, phase, place, useLoad, when, type Analysis, type DecisionGroup } from "../data";
import { lineShape, stretch, type Station } from "../lines";
import type { MapLabel, MapStop } from "../MapView";
import { go, link, WORK_TABS, type WorkTab } from "../router";
import { Loading, Panel, Problem, Tag, useMapLayers, type Layers } from "../ui";
import { Impact } from "./work/Impact";
import { Field, Notice, Period, PublishBar } from "./work/Rest";

/** What the map is asked to show beyond the work itself. */
export type Focus = { kind: "question"; id: string } | { kind: "line"; routeId: string } | { kind: "temp"; index: number } | null;
export type Answer = "affected" | "served" | null;

const TAB_NAME: Record<WorkTab, string> = { impact: "Impact", perioada: "Perioadă", anunt: "Anunț", teren: "Pe teren" };
const NEXT: Partial<Record<WorkTab, [WorkTab, string]>> = {
  impact: ["perioada", "Compară perioadele"],
  perioada: ["anunt", "Pregătește anunțul"],
  anunt: ["teren", "Vezi ce s-a întâmplat pe teren"],
};

/** A question is answered when every stop it covers has a decision, and they all agree. */
export function answerOf(g: DecisionGroup, a: Analysis): Answer {
  const by = new Map(a.stops.map((s) => [`${s.stopId}|${s.routeId}|${s.directionId}`, s.confirmed]));
  const v = g.rows.map((r) => by.get(`${r.stopId}|${r.routeId}|${r.directionId}`));
  return v.every((x) => x === true) ? "affected" : v.every((x) => x === false) ? "served" : null;
}

const coordsOf = (g: { type: string; coordinates?: unknown } | undefined): Position[] =>
  !g ? [] : g.type === "LineString" ? (g.coordinates as Position[]) : g.type === "MultiLineString" ? (g.coordinates as Position[][]).flat() : [];

/** Two names on the map should not sit on each other: the western one reads to the left, the eastern to the right. */
function sides(a: Station, b: Station): [MapLabel["place"], MapLabel["place"]] {
  const dx = Math.abs(a.lon - b.lon) * 0.7, dy = Math.abs(a.lat - b.lat);
  return dx >= dy ? (a.lon < b.lon ? ["left", "right"] : ["right", "left"]) : (a.lat > b.lat ? ["top", "bottom"] : ["bottom", "top"]);
}

/**
 * One work, from the request to the street. This is the only place with a sequence:
 * who loses service → when it hurts least → what riders are told → what vehicles really did.
 */
export function Work({ id, tab, q }: { id: string; tab: WorkTab; q?: string }) {
  const closure = useLoad(() => app.closure(id), id);
  const analysis = useLoad(() => app.analysis(id), id);
  const impact = useLoad(() => app.impact(id), id);
  const notice = useLoad(() => app.notice(id), id);
  const overview = useLoad(app.overview);
  const net = useNetwork();
  const [focus, setFocus] = useState<Focus>(q ? { kind: "question", id: q } : null);
  const [hover, setHover] = useState<Station | null>(null);
  const [published, setPublished] = useState(false);

  const c = closure.data, a = analysis.data;
  const groups = a?.decisionGroups ?? [];
  const answers = useMemo(() => new Map(groups.map((g) => [g.id, a ? answerOf(g, a) : null] as const)), [groups, a]);
  const open = groups.filter((g) => !answers.get(g.id)).length;
  const isPublished = c?.status === "published" || published;

  // an unanswered question opens by itself, so the first thing on screen is the thing to do
  const firstOpen = groups.find((g) => !answers.get(g.id))?.id;
  useEffect(() => { if (tab === "impact" && !q && firstOpen) setFocus((f) => f ?? { kind: "question", id: firstOpen }); }, [tab, q, firstOpen]);
  useEffect(() => { if (tab !== "impact") setFocus(null); }, [tab]);

  const answer = async (g: DecisionGroup, affected: boolean) => {
    const next = await app.decideStops(id, g.rows.map((r) => ({ ...r, confirmed: affected })));
    analysis.set(next);
    impact.reload(); notice.reload();
  };

  /* ---------- the map follows what the panel is talking about ---------- */
  const layers = useMemo<Layers>(() => {
    if (!c) return {};
    const pts = coordsOf(c.geometry);
    const mid = pts[Math.floor(pts.length / 2)];
    const work: MapLabel[] = mid ? [{ id: "work", lon: mid[0], lat: mid[1], text: place(c.title.ro), tone: "work", place: "top" }] : [];
    const closures = [{ id: c.id, geometry: c.geometry, selected: true }];
    const hov: MapLabel[] = hover ? [{ id: "hover", lon: hover.lon, lat: hover.lat, text: hover.name, tone: "stop", place: "top" }] : [];

    if (focus?.kind === "question" && net) {
      const g = groups.find((x) => x.id === focus.id);
      const shape = g && lineShape(net, g.routeId);
      const st = shape && stretch(shape, new Set(g!.rows.map((r) => r.stopId)));
      if (g && shape && st) {
        const ans = answers.get(g.id);
        const tone: MapStop["tone"] = ans === "affected" ? "closed" : ans === "served" ? "served" : "ask";
        const [pa, pb] = sides(st.from, st.to);
        const ends = [shape.stations[0], shape.stations[shape.stations.length - 1]].filter((s) => s !== st.from && s !== st.to);
        return {
          closures, highlight: [g.routeId], segment: st.coords,
          stops: shape.stations.slice(st.first, st.last + 1).map((s) => ({ id: s.ids[0], name: s.name, lon: s.lon, lat: s.lat, tone })),
          labels: [
            ...work,
            { id: "from", lon: st.from.lon, lat: st.from.lat, text: st.from.name, tone: "stop" as const, place: pa },
            { id: "to", lon: st.to.lon, lat: st.to.lat, text: st.to.name, tone: "stop" as const, place: pb },
            ...ends.map((s, i) => ({ id: `end${i}`, lon: s.lon, lat: s.lat, text: s.name, tone: "end" as const, place: "bottom" as const })),
            ...hov,
          ],
          fit: { key: `${id}:q:${g.id}`, points: st.coords },
        };
      }
    }

    if (focus?.kind === "line" && net) {
      const shape = lineShape(net, focus.routeId);
      if (shape) {
        const closed = new Set((notice.data?.sections ?? []).filter((s) => s.routeId === focus.routeId).flatMap((s) => s.stopsNotServed.map((x) => x.stopId)));
        const first = shape.stations[0], last = shape.stations[shape.stations.length - 1];
        const [pa, pb] = sides(first, last);
        return {
          closures, highlight: [focus.routeId],
          stops: shape.stations.map((s) => ({ id: s.ids[0], name: s.name, lon: s.lon, lat: s.lat, tone: s.ids.some((x) => closed.has(x)) ? "closed" as const : "served" as const })),
          labels: [...work, { id: "a", lon: first.lon, lat: first.lat, text: first.name, tone: "stop", place: pa }, { id: "b", lon: last.lon, lat: last.lat, text: last.name, tone: "stop", place: pb }, ...hov],
          fit: { key: `${id}:l:${focus.routeId}`, points: shape.path },
        };
      }
    }

    if (focus?.kind === "temp") {
      const t = c.temporaryRoutes?.[focus.index];
      const path = t?.geometry?.coordinates;
      if (t && path?.length) {
        return {
          closures, highlight: c.routeIds, detour: path,
          labels: [...work, { id: "t", lon: path[path.length - 1][0], lat: path[path.length - 1][1], text: `${t.shortName} · linie temporară`, tone: "stop", place: "top" }],
          fit: { key: `${id}:t:${focus.index}`, points: [...path, ...pts] },
        };
      }
    }

    // the work itself: its lines in colour and, in red, the stations left with no service at all
    const byId = new Map((net?.stops ?? []).map((s) => [s.id, s]));
    const seen = new Set<string>();
    const stops: MapStop[] = (notice.data?.stopsWithNoService ?? []).flatMap((s) => {
      const p = byId.get(s.stopId);
      const key = p ? `${s.name}|${p.lon.toFixed(3)}|${p.lat.toFixed(3)}` : "";
      if (!p || seen.has(key)) return [];
      seen.add(key);
      return [{ id: s.stopId, name: s.name, lon: p.lon, lat: p.lat, tone: "closed" as const }];
    });
    return {
      closures, highlight: c.routeIds, stops, labels: work,
      fit: { key: `${id}:${stops.length ? "full" : "bare"}`, points: [...pts, ...stops.map((s) => [s.lon, s.lat])], maxZoom: 14.4 },
    };
  }, [c, net, focus, hover, groups, answers, notice.data, id]);
  useMapLayers(layers);

  if (closure.error) return <Panel head={<Back />}><Problem>Lucrarea nu s-a încărcat ({closure.error}). Verificați adresa sau întoarceți-vă la listă.</Problem></Panel>;
  if (!c) return <Panel head={<Back />}><Loading rows={4} /></Panel>;

  const now = overview.data?.at;
  const done: Partial<Record<WorkTab, boolean>> = { impact: !!a && open === 0, anunt: isPublished };
  const next = NEXT[tab];

  return (
    <Panel
      head={
        <>
          <div className="flex items-center justify-between gap-3">
            <Back />
            {isPublished ? <Tag tone="green">Publicată</Tag> : <Tag tone="closure">Nepublicată</Tag>}
          </div>
          <h1 className="mt-2 text-lg font-semibold leading-snug tracking-tight">{c.title.ro}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-muted-foreground">
            <span className="tabular">{when(c.window)}{now ? ` · ${phase(c.window, now)}` : ""}</span>
            <span className="flex flex-wrap gap-1">{c.routeIds.map((r) => <LineBadge key={r} routeId={r} />)}</span>
          </div>
          <nav aria-label="Etapele lucrării" className="-mx-6 -mb-4 mt-4 flex border-t px-4">
            {WORK_TABS.map((t, i) => (
              <a key={t} {...link({ page: "lucrare", id, tab: t })} aria-current={t === tab ? "step" : undefined}
                className={cn("relative flex flex-1 items-center justify-center gap-1.5 py-3 text-sm outline-none transition-colors focus-visible:bg-muted",
                  t === tab ? "font-semibold text-foreground" : "text-muted-foreground hover:text-foreground")}>
                {done[t]
                  ? <span className="grid size-[18px] place-items-center rounded-full bg-primary text-primary-foreground"><Check className="size-3" strokeWidth={3} /><span className="sr-only">gata:</span></span>
                  : <span className={cn("tabular grid size-[18px] place-items-center rounded-full text-[0.6875rem] font-semibold", t === tab ? "bg-foreground text-background" : "bg-muted text-muted-foreground")}>{i + 1}</span>}
                {TAB_NAME[t]}
                {t === tab && <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-foreground" />}
              </a>
            ))}
          </nav>
        </>
      }
      foot={tab === "anunt" ? <PublishBar id={id} openQuestions={open} published={isPublished} onPublished={() => { setPublished(true); closure.reload(); }} /> : next && !(tab === "impact" && open > 0) && (
        <Button className="h-11 w-full rounded-xl text-base" onClick={() => go({ page: "lucrare", id, tab: next[0] })}>
          {next[1]} <ArrowRight className="size-4" />
        </Button>
      )}
    >
      {tab === "impact" && <Impact c={c} analysis={a} error={analysis.error} impact={impact.data} notice={notice.data} answers={answers} focus={focus} setFocus={setFocus} onHover={setHover} onAnswer={answer} />}
      {tab === "perioada" && <Period id={id} c={c} />}
      {tab === "anunt" && <Notice id={id} c={c} notice={notice.data} published={isPublished} />}
      {tab === "teren" && <Field id={id} c={c} />}
    </Panel>
  );
}

function Back() {
  return (
    <a {...link({ page: "lucrari" })} className="-ml-1 inline-flex items-center gap-1 rounded-md px-1 text-sm text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
      <ArrowLeft className="size-3.5" /> Lucrări
    </a>
  );
}
