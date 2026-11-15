import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, NotebookText, Pause, Play, RotateCcw, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Cursor, out, prog, reveal } from "@/film/kit";
import { BEATS, STEPS, type Step, type Target } from "./script";

/**
 * Guided demo: the pitch played on the real screens, in the style of the landing film.
 * A cursor travels to what the presenter points at, the words to say light up as they would be spoken,
 * and a note says where to point. It only navigates and opens things: nothing it does writes to the server.
 */

const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const RATE = 0.4; // seconds per spoken word, about 150 words a minute
const TRAVEL = 0.9; // seconds for the cursor to reach its target

const wordsOf = (s: string) => s.split(/\s+/).filter(Boolean);
const fill = (s: string, v: Record<string, string>) => s.replace(/\{(\w+)\}/g, (_, k: string) => v[k] ?? "…");
const durOf = (s: Step, text: string) => 0.5 + wordsOf(text).length * RATE + (s.hold ?? 1.4);

function nav(url: string) {
  if (location.pathname + location.search === url) return;
  history.pushState(null, "", url);
  dispatchEvent(new PopStateEvent("popstate"));
}

const textOf = (el: Element) => `${el.getAttribute("aria-label") ?? ""} ${el.textContent ?? ""}`.replace(/\s+/g, " ");
const hit = (el: Element, tg: Target) => tg.text == null || (typeof tg.text === "string" ? textOf(el).includes(tg.text) : tg.text.test(textOf(el)));
const shown = (el: Element) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };

/** The smallest visible element that matches: a selector, a text, or both. */
export function find(tg: Target): HTMLElement | null {
  const root = tg.within ? document.querySelector(tg.within) : document.body;
  if (!root) return null;
  let all = Array.from(root.querySelectorAll<HTMLElement>(tg.sel ?? "*")).filter((el) => !el.closest("[data-demo-ui]") && hit(el, tg) && shown(el));
  if (!tg.sel && tg.text != null) all = all.filter((el) => !Array.from(el.children).some((c) => hit(c, tg)));
  return all[tg.nth ?? 0] ?? null;
}

type Phase = "intro" | "seek" | "run" | "end";

declare global {
  interface Window { __demo?: { i: number; phase: Phase; found: boolean; text: string; go: (k: number) => void; pause: () => void } }
}
type Pt = { x: number; y: number };

export function Demo({ onExit }: { onExit: () => void }) {
  const [phase, setPhase] = useState<Phase>("intro");
  const [i, setI] = useState(0);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [notes, setNotes] = useState(true);
  const [el, setEl] = useState<HTMLElement | null>(null);
  const [vals, setVals] = useState<Record<string, string>>({});
  const [top, setTop] = useState(false);
  const from = useRef<Pt>({ x: innerWidth * 0.55, y: innerHeight * 0.45 });
  const last = useRef<Pt>(from.current);
  const clicked = useRef(false);
  const entered = useRef(false);
  const flipped = useRef(-1);
  const card = useRef<HTMLDivElement>(null);

  const step = STEPS[i];
  const beat = BEATS.find((b) => b.n === step.beat)!;
  const text = fill(step.say, vals);
  const dur = durOf(step, text);

  // warm the first screen behind the intro card
  // (deferred: this effect runs before the router's own listener is attached)
  useEffect(() => {
    const id = window.setTimeout(() => { if (STEPS[0].url) { history.replaceState(null, "", STEPS[0].url); dispatchEvent(new PopStateEvent("popstate")); } }, 0);
    return () => clearTimeout(id);
  }, []);

  // enter a step: go to its screen, wait for its target (screens can take 10 s after a pause), then run
  useEffect(() => {
    if (phase !== "seek") return;
    const s = STEPS[i];
    document.querySelectorAll<HTMLDialogElement>("dialog[open]").forEach((d) => d.close()); // the QR of the step before
    let delay = 0;
    if (s.url) {
      // the replay reads ?redare only when its page mounts: leave and come back to start it again
      if (s.fresh && entered.current && location.pathname === s.url.split("?")[0]) { nav("/app/linii"); delay = 150; }
      if (delay) window.setTimeout(() => nav(s.url!), delay); else nav(s.url);
    }
    entered.current = true;
    setEl(null); setVals(s.defaults ?? {}); setT(0);
    clicked.current = false;
    from.current = last.current;
    if (!s.target) { setPhase("run"); return; }
    let alive = true;
    const t0 = performance.now();
    const poll = () => {
      if (!alive) return;
      const e = find(s.target!);
      if (e) {
        const r = e.getBoundingClientRect();
        if (r.top < 60 || r.bottom > innerHeight - 60) e.scrollIntoView({ block: "center", behavior: calm ? "auto" : "smooth" });
        window.setTimeout(() => { if (!alive) return; setEl(e); setVals({ ...s.defaults, ...s.fill?.(e) }); setPhase("run"); }, s.settle ?? 350);
        return;
      }
      if (performance.now() - t0 > (s.wait ?? 15_000)) { setPhase("run"); return; } // go on without it rather than stall
      window.setTimeout(poll, 250);
    };
    const first = window.setTimeout(poll, (s.url ? 300 : 50) + delay);
    return () => { alive = false; clearTimeout(first); };
  }, [i, phase]);

  // for the screenshot and recording scripts: where the demo is, and a way to jump
  useEffect(() => {
    window.__demo = { i, phase, found: !!el, text, go: (k: number) => { setI(Math.max(0, Math.min(STEPS.length - 1, k))); setPhase("seek"); setPlaying(true); }, pause: () => setPlaying(false) };
  });

  // the clock of the step
  useEffect(() => {
    if (phase !== "run" || !playing) return;
    let raf = 0, prev = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - prev) / 1000);
      prev = now;
      setT((x) => x + dt);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [phase, playing]);

  const next = () => { if (i + 1 < STEPS.length) { setI(i + 1); setPhase("seek"); } else setPhase("end"); };
  const back = () => { setI(Math.max(0, i - 1)); setPhase("seek"); };
  const jump = (n: number) => { setI(STEPS.findIndex((s) => s.beat === n)); setPhase("seek"); setPlaying(true); };
  const exit = () => { if (location.pathname === "/app/demo") history.replaceState(null, "", "/app"); dispatchEvent(new PopStateEvent("popstate")); onExit(); };

  useEffect(() => {
    if (phase !== "run") return;
    if (step.click && el && !clicked.current && t >= (calm ? 0.2 : TRAVEL + 0.05)) { clicked.current = true; el.click(); }
    if (t >= dur) next();
  });

  // keys: space pauses, arrows step, escape leaves
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const tg = e.target as HTMLElement | null;
      if (tg?.closest("input, textarea, select, [contenteditable], [role=slider]")) return;
      if (e.key === " " && phase !== "intro" && phase !== "end") { e.preventDefault(); setPlaying((p) => !p); }
      else if (e.key === "ArrowRight" && phase !== "intro") { e.preventDefault(); next(); }
      else if (e.key === "ArrowLeft" && phase !== "intro") { e.preventDefault(); back(); }
      else if (e.key === "Escape" && !document.querySelector("dialog[open]")) exit(); // Escape first closes the QR
    };
    addEventListener("keydown", on);
    return () => removeEventListener("keydown", on);
  });

  // where things are on screen now
  const r = phase === "run" && el?.isConnected ? el.getBoundingClientRect() : null;
  if (r) {
    const wide = r.width > 260;
    last.current = { x: wide ? r.left + Math.min(r.width * 0.3, 140) : r.left + r.width / 2, y: r.top + r.height / 2 };
  }
  const to = last.current;

  // the caption moves to the top when it would cover what it points at
  useLayoutEffect(() => {
    if (!r || !card.current || flipped.current === i) return;
    const c = card.current.getBoundingClientRect();
    const covers = !(r.right < c.left || r.left > c.right || r.bottom < c.top || r.top > c.bottom);
    if (covers) { flipped.current = i; setTop((x) => !x); } // at most once per step, so it never flickers
  }, [r?.top, r?.left, i]); // eslint-disable-line react-hooks/exhaustive-deps

  const words = wordsOf(text);
  const lineStyle = calm ? undefined : reveal(t, 0, Infinity, 0.5);
  const pad = 6;

  return (
    <div data-demo-ui className="pointer-events-none fixed inset-0 z-[60]">
      {r && (
        <div aria-hidden className="absolute rounded-xl transition-[opacity] duration-300"
          style={{ left: r.left - pad, top: r.top - pad, width: r.width + pad * 2, height: r.height + pad * 2,
            opacity: out(prog(t, calm ? 0 : TRAVEL * 0.6, 0.4)),
            boxShadow: "0 0 0 2px var(--green), 0 0 0 7px color-mix(in oklch, var(--green) 22%, transparent), 0 0 0 100vmax oklch(0.2 0.012 165 / 0.14)" }} />
      )}

      {(phase === "run" || phase === "seek") && (
        <Cursor t={phase === "run" ? t : 0} keys={[
          { t: 0, x: from.current.x, y: from.current.y },
          { t: calm ? 0.01 : TRAVEL, x: to.x, y: to.y, click: phase === "run" && !!step.click },
          { t: 9999, x: to.x, y: to.y },
        ]} />
      )}

      {phase === "intro" && (
        <div className="pointer-events-auto absolute inset-0 grid place-items-center bg-foreground/25 p-4 backdrop-blur-[2px]">
          <div role="dialog" aria-modal="true" aria-labelledby="demo-title" className="w-full max-w-lg rounded-2xl border bg-card p-7 shadow-float">
            <p className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">Demo ghidat</p>
            <h2 id="demo-title" className="mt-2 text-2xl font-semibold tracking-tight text-balance">Prezentarea, pe ecranele reale.</h2>
            <p className="mt-3 leading-relaxed text-muted-foreground">
              Trei minute, șapte pași. Jos apar cuvintele de spus, în ritmul vorbirii. Cursorul arată ce se apasă, iar nota spune unde arăți.
              Platforma e publică, așa că demo-ul nu publică și nu răspunde la nimic.
            </p>
            <div className="mt-6 flex flex-wrap items-center gap-3">
              <button type="button" autoFocus onClick={() => { setPhase("seek"); setPlaying(true); }}
                className="inline-flex items-center gap-2 rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-card outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
                <Play className="size-4" /> Pornește demo-ul
              </button>
              <button type="button" onClick={exit} className="rounded-full px-4 py-2.5 text-sm font-medium text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">Nu acum</button>
            </div>
            <p className="mt-5 text-xs text-muted-foreground">Spațiu: pauză · ← →: pasul anterior sau următor · Esc: ieși</p>
          </div>
        </div>
      )}

      {phase === "end" && (
        <div className="pointer-events-auto absolute inset-0 grid place-items-center bg-foreground/25 p-4 backdrop-blur-[2px]">
          <div role="dialog" aria-modal="true" aria-labelledby="demo-end" className="w-full max-w-lg rounded-2xl border bg-card p-7 text-center shadow-float">
            <p className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">Gata</p>
            <h2 id="demo-end" className="mt-2 text-3xl font-semibold tracking-tight">„Mulțumim. Întrebări?”</h2>
            <p className="mt-3 text-muted-foreground">După fiecare juriu: resetezi demo-ul și redeschizi linia 23 la 9:20.</p>
            <div className="mt-6 flex flex-wrap justify-center gap-3">
              <button type="button" autoFocus onClick={() => { setI(0); setPhase("seek"); setPlaying(true); }}
                className="inline-flex items-center gap-2 rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-card outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
                <RotateCcw className="size-4" /> Încă o dată
              </button>
              <button type="button" onClick={exit} className="rounded-full border px-5 py-2.5 text-sm font-medium outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring">Înapoi în platformă</button>
            </div>
          </div>
        </div>
      )}

      {(phase === "run" || phase === "seek") && (
        <div ref={card} role="region" aria-label="Demo ghidat"
          className={cn("pointer-events-auto absolute left-3 right-3 rounded-2xl border bg-card/95 p-4 shadow-float backdrop-blur md:left-auto md:right-5 md:w-[min(46rem,calc(100vw-37rem))] md:p-5",
            top ? "top-3 md:top-5" : "bottom-3 md:bottom-5")}>
          <div className="flex items-center gap-1.5">
            <ol className="flex flex-1 flex-wrap gap-1" aria-label="Pașii prezentării">
              {BEATS.map((b) => (
                <li key={b.n}>
                  <button type="button" onClick={() => jump(b.n)} aria-current={b.n === step.beat ? "step" : undefined} title={b.title}
                    className={cn("h-7 rounded-full px-2.5 text-xs font-semibold tabular outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                      b.n === step.beat ? "bg-foreground text-background" : b.n < step.beat ? "bg-green-soft text-foreground" : "bg-muted text-muted-foreground hover:text-foreground")}>
                    {b.n === step.beat ? `${b.n} · ${b.title}` : b.n}
                  </button>
                </li>
              ))}
            </ol>
            <button type="button" onClick={() => setNotes((x) => !x)} aria-pressed={notes} title="Notele prezentatorului"
              className={cn("grid size-8 place-items-center rounded-full outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring", notes ? "bg-green-soft text-foreground" : "text-muted-foreground hover:bg-muted")}>
              <NotebookText className="size-4" /><span className="sr-only">Notele prezentatorului</span>
            </button>
            <button type="button" onClick={exit} className="grid size-8 place-items-center rounded-full text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
              <X className="size-4" /><span className="sr-only">Ieși din demo</span>
            </button>
          </div>

          <p key={i} aria-live="polite" className="mt-3 text-[1.1875rem] font-medium leading-snug tracking-[-0.01em] text-pretty md:text-[1.3125rem]" style={lineStyle}>
            {words.map((w, k) => {
              const x = phase === "run" ? out(prog(t, 0.35 + k * RATE, 0.3)) : 0;
              return (
                <span key={k} className={cn(/\d/.test(w) && "font-semibold")} style={{ opacity: 0.3 + 0.7 * x, color: x > 0.5 && /\d/.test(w) ? "var(--accent-foreground)" : undefined }}>
                  {w}{k < words.length - 1 ? " " : ""}
                </span>
              );
            })}
          </p>

          {notes && step.note && (
            <p className="mt-2.5 text-sm leading-relaxed text-muted-foreground"><span className="font-semibold text-foreground">Arăți: </span>{step.note}</p>
          )}
          {notes && step.click && step.press && (
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground"><span className="font-semibold text-foreground">Erol apasă: </span>{step.press}</p>
          )}

          <div className="mt-3.5 flex items-center gap-2">
            <button type="button" onClick={back} disabled={i === 0} className="grid size-8 place-items-center rounded-full border outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40">
              <ChevronLeft className="size-4" /><span className="sr-only">Pasul anterior</span>
            </button>
            <button type="button" onClick={() => setPlaying((p) => !p)} className="grid size-9 place-items-center rounded-full bg-primary text-primary-foreground shadow-card outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
              {playing ? <Pause className="size-4" /> : <Play className="size-4" />}<span className="sr-only">{playing ? "Pauză" : "Continuă"}</span>
            </button>
            <button type="button" onClick={next} className="grid size-8 place-items-center rounded-full border outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring">
              <ChevronRight className="size-4" /><span className="sr-only">Pasul următor</span>
            </button>
            <div className="relative ml-1 h-1.5 flex-1 overflow-hidden rounded-full bg-muted" aria-hidden>
              <div className="h-full rounded-full bg-primary" style={{ width: `${phase === "run" ? Math.min(100, (t / dur) * 100) : 0}%` }} />
            </div>
            <span className="tabular shrink-0 whitespace-nowrap text-right text-xs text-muted-foreground">
              {phase === "seek" ? "Se încarcă ecranul…" : `${beat.at} în pitch · ${i + 1}/${STEPS.length}`}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
