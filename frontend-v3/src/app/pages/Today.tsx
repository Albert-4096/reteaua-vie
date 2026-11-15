import { useMemo, useState } from "react";
import { ArrowRight, Construction } from "lucide-react";
import type { Position } from "geojson";
import { LineBadge } from "@/landing/LineBadge";
import { useNetwork } from "@/lib/network";
import { app, count, fmt, hhmm, losses, phase, place, registrySpan, seenByLine, spread, useLoad, weekday, when, type ClosureSummary } from "../data";
import type { MapLabel } from "../MapView";
import { link, type Route } from "../router";
import { SeenBar } from "../Measured";
import { ReplayBar, ReplayButton, silentLines, useReplay } from "../Replay";
import { Kind, LiveDot, Loading, Panel, Problem, Section, Tag, Title, useMapLayers, type Layers } from "../ui";
import { answerOf } from "./Work";

const coords = (c: ClosureSummary): Position[] => (!c.geometry ? [] : c.geometry.type === "LineString" ? c.geometry.coordinates : c.geometry.coordinates.flat());

/** `check`: a signal a person should look at, not yet a confirmed task (an off-route run may be a depot run). */
type Task = { key: string; lead: React.ReactNode; title: string; detail: string; numbers?: string; owner: string; action: string; to: Route; closureId?: string; check?: boolean };

/**
 * The first screen of the day: what waits for a person, then the network as it is right now.
 * The map beside it is the live one: vehicles in their line colours, works in red, and, dashed,
 * the lines the timetable lists but the live data does not show.
 */
export function Today() {
  const o = useLoad(app.overview);
  const closures = useLoad(app.works);
  const missing = useLoad(app.missing, "", 60_000);
  const vehicles = useLoad(app.vehicles, "", 15_000);
  const dev = useLoad(app.deviations, "", 60_000);
  const reg = useLoad(app.registry);
  const net = useNetwork();
  const [hover, setHover] = useState<string | null>(null);
  const replay = useReplay();

  const now = o.data?.at;
  const waiting = (closures.data ?? []).filter((c) => c.status !== "published");
  const ids = waiting.map((c) => c.id).join();
  const analyses = useLoad(() => Promise.all(waiting.map((c) => app.analysis(c.id).catch(() => null))), ids);
  const noVehicle = (missing.data?.routes ?? []).filter((r) => r.state === "fara_vehicul" && !r.decision);
  const current = (closures.data ?? []).filter((c) => now && phase(c.window, now) === "în desfășurare");
  const offRoute = (dev.data?.groups ?? []).filter((g) => g.classification === "fara_anunt");
  const worst = [...seenByLine(reg.data)].map(([routeId, trips]) => ({ routeId, trips })).filter((l) => l.trips.missed > 0).sort((a, b) => (a.trips.share ?? 1) - (b.trips.share ?? 1)).slice(0, 3);

  const tasks: Task[] = [
    ...waiting.map((c, i): Task => {
      const a = analyses.data?.[i];
      const open = a ? a.decisionGroups.filter((g) => !answerOf(g, a)).length : 0;
      const lead = <span className="grid size-9 place-items-center rounded-md bg-closure-soft text-closure-ink"><Construction className="size-[18px]" strokeWidth={1.8} /></span>;
      if (c.status === "draft") return { key: c.id, lead, title: "Anunț citit, impact necalculat", detail: place(c.title.ro), owner: "Primărie · mobilitate", action: "Continuă", to: { page: "nou", c: c.id }, closureId: c.id };
      return open > 0
        ? { key: c.id, lead, title: open === 1 ? "O întrebare despre stații" : `${open} întrebări despre stații`, detail: place(c.title.ro), owner: "Primărie · mobilitate", action: "Răspunde", to: { page: "lucrare", id: c.id, tab: "impact" }, closureId: c.id }
        : { key: c.id, lead, title: "Lucrare analizată, nepublicată", detail: place(c.title.ro), numbers: losses(c), owner: "STPT · informare călători", action: "Deschide", to: { page: "lucrare", id: c.id, tab: "impact" }, closureId: c.id };
    }),
    ...noVehicle.map((r): Task => ({
      key: r.routeId, lead: <LineBadge routeId={r.routeId} label={r.shortName} size="lg" />,
      title: `Linia ${r.shortName} nu are vehicul în datele live`,
      detail: `${r.tripsObserved} din ${count(r.tripsInService, "cursă", "curse")} din orar, ${missing.data ? `${hhmm(missing.data.window.start)}–${hhmm(missing.data.window.end)}` : "ultima oră"}: nu circulă, sau lipsesc date`,
      owner: "STPT · dispecerat", action: "Verifică", to: { page: "linii", routeId: r.routeId },
    })),
    ...offRoute.map((g): Task => ({
      key: `off-${g.routeId}-${g.firstAt}`, lead: <LineBadge routeId={g.routeId} label={g.shortName} size="lg" />,
      title: `Linia ${g.shortName}: posibilă abatere de la traseu`,
      detail: `${hhmm(g.firstAt)}${g.street ? `, ${g.street}` : ""} · fără anunț găsit`,
      owner: "STPT · dispecerat", action: "Verifică", to: { page: "linii", routeId: g.routeId }, check: true,
    })),
  ];

  // everything but the vehicles: it keeps its identity while a replay moves them four times a second
  const still = useMemo<Layers>(() => {
    const labels: MapLabel[] = spread(current.flatMap((c) => {
      const p = coords(c);
      const mid = p[Math.floor(p.length / 2)];
      return mid ? [{ id: c.id, lon: mid[0], lat: mid[1], text: place(c.title.ro), tone: "work" as const }] : [];
    }));
    // dashed: now, the lines with no vehicle in the live data; in the replay, the lines the recording never shows that day
    const ghost = replay.on ? silentLines(reg.data, replay.data).map((id) => ({ routeId: id, shortName: net?.byId.get(id)?.shortName ?? id })) : noVehicle;
    for (const r of ghost) {
      const path = net?.paths.find((p) => p.routeId === r.routeId)?.geometry.coordinates;
      const mid = path?.[Math.floor(path.length / 2)];
      if (mid) labels.push({ id: `ghost-${r.routeId}`, lon: mid[0], lat: mid[1], text: `${r.shortName} · fără vehicul`, tone: "ghost", place: "top" });
    }
    return {
      fit: { key: "city" },
      closures: current.map((c) => ({ id: c.id, geometry: c.geometry, selected: c.id === hover })),
      ghost: ghost.map((r) => r.routeId),
      labels,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [closures.data, now, missing.data, net, hover, replay.on, replay.data, reg.data]);
  const live = useMemo(() => (vehicles.data?.features ?? []).map((v) => ({ id: v.properties.vehicleId, lon: v.geometry.coordinates[0], lat: v.geometry.coordinates[1], routeId: v.properties.routeId })), [vehicles.data]);
  const layers = useMemo<Layers>(() => ({ ...still, vehicles: replay.on ? replay.vehicles : live, recorded: replay.on ? { stepMs: replay.stepMs } : null }), [still, live, replay.on, replay.vehicles, replay.stepMs]);
  useMapLayers(layers);

  const at = vehicles.data?.features[0]?.properties.updatedAt;
  const ready = !!closures.data && !!missing.data && !!analyses.data;

  return (
    <Panel head={<Title sub={now ? <>{weekday(now)}, {hhmm(now)} <span className="text-foreground/60">· ceas simulat</span></> : "Se citește ceasul…"}>Azi</Title>}>
      <Section title="Așteaptă un om" aside={ready ? tasks.filter((t) => !t.check).length : undefined}>
        {closures.error ? <Problem>Lista nu s-a încărcat ({closures.error}). Reîncărcați pagina.</Problem> : !ready ? <Loading rows={3} /> : tasks.length === 0 ? (
          <p className="text-sm leading-relaxed text-muted-foreground">Nimic de făcut acum: toate lucrările sunt publicate și fiecare linie din orar are vehicul în datele live.</p>
        ) : (
          <ul className="-mx-2 space-y-0.5">
            {tasks.map((t) => (
              <li key={t.key}>
                <a {...link(t.to)} onPointerEnter={() => setHover(t.closureId ?? null)} onPointerLeave={() => setHover(null)}
                  className="group block rounded-lg px-2 py-2.5 outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring">
                  <span className="flex items-center gap-3">
                    {t.lead}
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium leading-snug">{t.title}</span>
                      <span className="tabular line-clamp-2 text-sm leading-snug text-muted-foreground">{t.detail}</span>
                      {!t.numbers && <span className="block text-xs text-muted-foreground">{t.check && <span className="font-medium text-foreground/80">de verificat · </span>}{t.owner}</span>}
                    </span>
                    <span className="inline-flex h-8 shrink-0 items-center gap-1 rounded-md border bg-card px-2.5 text-sm font-medium transition-colors group-hover:border-foreground/30">{t.action} <ArrowRight className="size-3.5" /></span>
                  </span>
                  {t.numbers && (
                    <span className="mt-1 block pl-12">
                      <span className="tabular block text-sm leading-snug text-foreground/80">{t.numbers}</span>
                      <span className="block text-xs text-muted-foreground">{t.owner}</span>
                    </span>
                  )}
                </a>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Orarul față de stradă" aside={<ReplayButton r={replay} />}>
        <ReplayBar r={replay} />
        {replay.on && replay.frame ? (
          <p className="flex items-center gap-2 text-sm">
            <span className="size-2 shrink-0 rounded-full bg-foreground/50" aria-hidden />
            <span className="tabular">{replay.frame.gap ? "Gol în înregistrare" : count(replay.vehicles.length, "vehicul", "vehicule")}, {weekday(replay.frame.t).split(",")[0]} la {hhmm(replay.frame.t)} · înregistrare</span>
          </p>
        ) : (
          <p className="flex items-center gap-2 text-sm">
            <LiveDot />
            <span className="tabular">{vehicles.data ? `${count(vehicles.data.features.length, "vehicul", "vehicule")} în datele live${at ? `, la ${hhmm(at)}` : ""}` : "Se citesc vehiculele…"}</span>
          </p>
        )}
        {o.data?.ghostDeparturesToday != null && (
          <p className="mt-2.5 text-sm leading-relaxed text-foreground/80">
            <span className="tabular font-semibold text-foreground">{fmt.format(o.data.ghostDeparturesToday)}</span> de plecări din orarul de azi nu au loc: o lucrare publicată a scos acele stații de pe traseul liniei.
          </p>
        )}
        {reg.data && worst.length > 0 && (
          <>
            <div className="mt-5 flex items-center justify-between gap-3">
              <p className="text-sm text-muted-foreground">Curse din orar văzute în datele live</p>
              <Kind k="measured" />
            </div>
            <ul className="-mx-2 mt-1.5">
              {worst.map((l) => (
                <li key={l.routeId}>
                  <a {...link({ page: "linii", routeId: l.routeId })} className="flex items-center gap-3 rounded-lg px-2 py-2 outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring">
                    <LineBadge routeId={l.routeId} size="lg" />
                    <span className="min-w-0 flex-1">
                      <span className="tabular block text-sm"><span className="font-semibold">{fmt.format(l.trips.observed)} din {fmt.format(l.trips.scheduled)}</span> <span className="text-muted-foreground">· {fmt.format(l.trips.missed)} nevăzute</span></span>
                      <SeenBar t={l.trips} className="mt-1.5" />
                    </span>
                  </a>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
              Din registrul zilnic al curselor, {registrySpan(reg.data)}, înregistrat la 15 secunde. Estimare din datele live, nu raportul oficial.{" "}
              <a {...link({ page: "linii" })} className="font-medium text-foreground underline underline-offset-4">Toate liniile</a>
            </p>
          </>
        )}
      </Section>

      <Section title="Lucrări în desfășurare" aside={closures.data && now ? current.length : undefined}>
        {!closures.data || !now ? <Loading rows={2} /> : current.length === 0 ? <p className="text-sm text-muted-foreground">Nicio lucrare nu închide acum o stradă cu transport public.</p> : (
          <ul className="-mx-2 space-y-0.5">
            {current.map((c) => (
              <li key={c.id}>
                <a {...link({ page: "lucrare", id: c.id, tab: "impact" })} onPointerEnter={() => setHover(c.id)} onPointerLeave={() => setHover(null)} onFocus={() => setHover(c.id)} onBlur={() => setHover(null)}
                  className="flex items-start gap-3 rounded-lg px-2 py-2.5 outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring">
                  <span className="mt-1.5 size-2.5 shrink-0 rounded-full bg-closure" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium leading-snug">{place(c.title.ro)}</span>
                    <span className="tabular block text-sm text-muted-foreground">{when(c.window)} · {count(c.routeIds.length, "linie", "linii")}</span>
                  </span>
                  {c.status === "draft" ? <Tag>Ciornă</Tag> : c.status !== "published" && <Tag tone="closure">Nepublicată</Tag>}
                </a>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </Panel>
  );
}
