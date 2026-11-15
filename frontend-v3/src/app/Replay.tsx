import { useContext, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { History, Pause, Play, X } from "lucide-react";
import { app, count, hhmm, weekday, type Registry, type Replay } from "./data";
import type { MapVehicle } from "./MapView";
import { MapSlotCtx } from "./ui";

/** One recorded minute stays on screen this long while playing: 4 minutes of street per second. */
const FRAME_MS = 250;
const calm = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

export type ReplayState = ReturnType<typeof useReplay>;

/**
 * Saturday morning as we recorded it, frame by frame, on the same map as the live vehicles.
 * Nothing is drawn that was not in the live data at that minute: a line with no vehicle stays empty.
 * The recording is fetched only when somebody asks for it.
 */
export function useReplay() {
  const [on, setOn] = useState(() => new URLSearchParams(location.search).has("redare"));
  const [data, setData] = useState<Replay | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [jumped, setJumped] = useState(true); // the slider was dragged: vehicles jump there, they do not glide

  useEffect(() => {
    if (!on || data) return;
    let alive = true;
    app.replay()
      .then((d) => { if (!alive) return; setData(d); setError(null); setI(0); setPlaying(!calm()); })
      .catch((e: Error) => alive && setError(e.message));
    return () => { alive = false; };
  }, [on, data]);

  const n = data?.frames.length ?? 0;
  useEffect(() => {
    if (!on || !playing || n === 0) return;
    const t = window.setInterval(() => { setJumped(false); setI((x) => Math.min(x + 1, n - 1)); }, FRAME_MS);
    return () => window.clearInterval(t);
  }, [on, playing, n]);
  useEffect(() => { if (n > 0 && i >= n - 1) setPlaying(false); }, [i, n]);

  const frame = on ? data?.frames[i] : undefined;
  const vehicles = useMemo<MapVehicle[]>(() => (frame?.vehicles ?? []).map((v) => ({ id: v[0], routeId: v[1] ?? "", lat: v[2], lon: v[3] })), [frame]);

  return {
    on, data, error, i, n, frame, vehicles, playing,
    stepMs: playing && !jumped ? FRAME_MS : 0,
    start: () => { setOn(true); setError(null); if (data) { setJumped(true); setPlaying(!calm()); } },
    stop: () => { setOn(false); setPlaying(false); },
    toggle: () => { if (i >= n - 1) { setJumped(true); setI(0); } setPlaying((p) => !p); },
    seek: (x: number) => { setJumped(true); setPlaying(false); setI(x); },
  };
}

/** Lines the timetable ran that day and the live data never showed: none of their trips seen, and in no frame of the replay. */
export function silentLines(reg: Registry | null, data: Replay | null): string[] {
  if (!reg || !data) return [];
  const entry = reg.entries.find((e) => e.date === data.window.start.slice(0, 10));
  const seen = new Set(data.frames.flatMap((f) => (f.vehicles ?? []).map((v) => v[1])));
  return (entry?.lines ?? []).filter((l) => l.tripsScheduledInRecording > 0 && l.tripsSeen === 0 && !seen.has(l.routeId)).map((l) => l.routeId);
}

/** The quiet way in: it sits in a section's title row and changes nothing until pressed. */
export function ReplayButton({ r }: { r: ReplayState }) {
  return (
    <button type="button" onClick={r.on ? r.stop : r.start} aria-pressed={r.on}
      className="-my-1 inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-sm font-medium text-foreground/80 outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
      {r.on ? <X className="size-3.5" /> : <History className="size-3.5" />}
      {r.on ? "Înapoi la acum" : "Redă sâmbătă dimineață"}
    </button>
  );
}

/** The time slider, over the map while the replay is on. On a line's page it also counts that line's vehicles. */
export function ReplayBar({ r, line }: { r: ReplayState; line?: { routeId: string; shortName: string } }) {
  const slot = useContext(MapSlotCtx);
  const d = r.data;
  const ever = useMemo(() => !!line && !!d && d.frames.some((f) => f.vehicles?.some((v) => v[1] === line.routeId)), [d, line?.routeId]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!r.on || !slot) return null;
  const f = r.frame;
  const mine = line && f?.vehicles ? f.vehicles.filter((v) => v[1] === line.routeId).length : 0;

  return createPortal(
    <section aria-label="Redarea înregistrării" className="absolute inset-x-2 bottom-2 z-10 mx-auto max-w-xl rounded-xl border bg-card/95 px-3 pb-2 pt-2.5 shadow-card backdrop-blur-sm md:inset-x-3 md:bottom-10 md:px-3.5 md:pb-2.5 md:pt-3">
      {r.error ? (
        <p className="flex items-center justify-between gap-3 text-sm">
          <span>Înregistrarea nu s-a încărcat ({r.error}).</span>
          <button type="button" onClick={r.stop} className="rounded-md px-2 py-1 font-medium underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-ring">Închide</button>
        </p>
      ) : !d || !f ? <p role="status" className="py-1 text-sm text-muted-foreground">Se încarcă înregistrarea de sâmbătă…</p> : (
        <>
          <div className="flex items-center gap-3">
            <button type="button" onClick={r.toggle} aria-label={r.playing ? "Pauză" : "Redă"}
              className="grid size-9 shrink-0 place-items-center rounded-full bg-foreground text-background outline-none transition-transform active:scale-95 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
              {r.playing ? <Pause className="size-4" fill="currentColor" strokeWidth={0} /> : <Play className="ml-0.5 size-4" fill="currentColor" strokeWidth={0} />}
            </button>
            <p className="min-w-0 flex-1 leading-tight">
              <span className="tabular text-base font-semibold">{hhmm(f.t)}</span>
              <span className="ml-2 text-sm text-muted-foreground"><span className="max-md:hidden">{weekday(f.t)} · </span>înregistrare<span className="md:hidden"> de {weekday(f.t).split(",")[0]}</span></span>
              <span className="tabular mt-0.5 block text-xs text-muted-foreground" aria-live="off">
                {f.gap ? "gol în înregistrare la acest minut" : `${count(r.vehicles.length, "vehicul", "vehicule")}${line ? "" : " în datele live"}`}
                {line && !f.gap && <> · <span className="font-medium text-foreground">linia {line.shortName}: {!ever ? "niciunul în tot intervalul" : mine === 0 ? "niciunul" : count(mine, "vehicul", "vehicule")}</span></>}
              </span>
            </p>
            <button type="button" onClick={r.stop} className="inline-flex h-8 shrink-0 items-center gap-1 rounded-md px-2 text-sm font-medium text-foreground/80 outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
              <span className="hidden sm:inline">Înapoi la acum</span><X className="size-4" /><span className="sr-only sm:hidden">Înapoi la acum</span>
            </button>
          </div>
          <input type="range" min={0} max={r.n - 1} step={1} value={r.i} onChange={(e) => r.seek(Number(e.target.value))}
            aria-label="Momentul din înregistrare" aria-valuetext={hhmm(f.t)} className="mt-1.5 block w-full cursor-pointer accent-[var(--primary)] md:mt-2.5" />
          <p className="tabular mt-0.5 flex justify-between gap-3 text-[0.6875rem] text-muted-foreground max-md:hidden">
            <span>{hhmm(d.window.start)}</span>
            <span className="hidden truncate sm:inline">{d.label.ro}, un cadru pe minut</span>
            <span>{hhmm(d.window.end)}</span>
          </p>
        </>
      )}
    </section>,
    slot,
  );
}
