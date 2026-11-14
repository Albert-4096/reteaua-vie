import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Pause, Play, RotateCcw } from "lucide-react";
import { useFilmData, useGeo } from "./data";
import { SCENES, TOTAL } from "./scenes";
import { prog } from "./kit";

declare global {
  interface Window { __film?: { ready: boolean; total: number; seek: (t: number) => void } }
}

const STARTS = SCENES.reduce<number[]>((a, s, i) => (a.push(i ? a[i - 1] + SCENES[i - 1].dur : 0), a), []);
const still = new URLSearchParams(location.search).get("film");

/** The product film: a 1280×720 stage scaled to its container, every frame a function of t. */
export function Film({ className }: { className?: string }) {
  const { data, error } = useFilmData();
  const g = useGeo(data);
  const box = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [t, setT] = useState(still ? Number(still) : 0);
  const [playing, setPlaying] = useState(!still);
  const [visible, setVisible] = useState(false);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setScale(e.contentRect.width / 1280));
    ro.observe(el);
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting), { threshold: 0.35 });
    io.observe(el);
    return () => { ro.disconnect(); io.disconnect(); };
  }, []);

  useEffect(() => {
    if (!playing || !visible || !g) return;
    let raf = 0, last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      setT((x) => (x + dt >= TOTAL ? 0 : x + dt));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, visible, g]);

  useEffect(() => {
    window.__film = { ready: !!g, total: TOTAL, seek: (x) => { setPlaying(false); setT(x); } };
  }, [g]);

  const i = Math.max(0, STARTS.findLastIndex((s) => t >= s));
  const local = t - STARTS[i];
  const scene = SCENES[i];
  const fade = 1 - prog(local, scene.dur - 0.35, 0.35);

  return (
    <div ref={box} className={className}>
      <div className="group relative aspect-video w-full overflow-hidden rounded-xl border bg-card shadow-float">
        <div className="dot-ground absolute left-0 top-0 origin-top-left" style={{ width: 1280, height: 720, transform: `scale(${scale})` }}>
          {data && g ? (
            <div key={scene.id} style={{ position: "absolute", inset: 0, opacity: fade, filter: `blur(${(1 - fade) * 6}px)` }}>
              {scene.render({ t: local, d: data, g })}
            </div>
          ) : (
            <div className="grid h-full place-items-center text-2xl text-muted-foreground">{error ? "Filmul are nevoie de API. Încercați din nou." : "Se pregătește filmul…"}</div>
          )}
        </div>

        {!still && (
          <div className="absolute inset-x-0 bottom-0 flex items-center gap-3 bg-gradient-to-t from-black/25 to-transparent px-4 pb-3 pt-10 opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-within:opacity-100">
            <button type="button" onClick={() => setPlaying((p) => !p)} aria-label={playing ? "Pauză" : "Redă"}
              className="grid size-9 place-items-center rounded-full bg-white/95 text-foreground shadow-card">
              {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
            </button>
            <div className="relative h-1.5 flex-1 cursor-pointer rounded-full bg-white/50" role="slider" aria-label="Poziția în film"
              aria-valuemin={0} aria-valuemax={Math.round(TOTAL)} aria-valuenow={Math.round(t)} tabIndex={0}
              onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); setT(((e.clientX - r.left) / r.width) * TOTAL); }}
              onKeyDown={(e) => { if (e.key === "ArrowRight") setT((x) => Math.min(TOTAL - 0.1, x + 3)); if (e.key === "ArrowLeft") setT((x) => Math.max(0, x - 3)); }}>
              <div className="h-full rounded-full bg-white" style={{ width: `${(t / TOTAL) * 100}%` }} />
              {STARTS.slice(1).map((s) => <span key={s} className="absolute top-0 h-full w-0.5 bg-black/20" style={{ left: `${(s / TOTAL) * 100}%` }} />)}
            </div>
            <button type="button" onClick={() => { setT(0); setPlaying(true); }} aria-label="De la început"
              className="grid size-9 place-items-center rounded-full bg-white/95 text-foreground shadow-card">
              <RotateCcw className="size-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
