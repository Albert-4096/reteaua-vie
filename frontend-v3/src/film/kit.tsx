import type { CSSProperties, ReactNode } from "react";

/* Every frame of the film is a pure function of time, so it can pause, seek and be recorded frame by frame. */

export const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
export const prog = (t: number, start: number, dur: number) => clamp01((t - start) / dur);
export const out = (x: number) => (x >= 1 ? 1 : 1 - Math.pow(2, -10 * x)); // exponential ease-out
export const inOut = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
export const lerp = (a: number, b: number, x: number) => a + (b - a) * x;

/** Enter (blur + rise) and leave, both driven by t. */
export function reveal(t: number, at: number, leaveAt = Infinity, dur = 0.7): CSSProperties {
  const a = out(prog(t, at, dur));
  const b = inOut(prog(t, leaveAt, 0.45));
  const v = a * (1 - b);
  return { opacity: v, filter: `blur(${(1 - a) * 10 + b * 8}px)`, transform: `translateY(${(1 - a) * 18 - b * 10}px)` };
}

/** Kinetic headline: words arrive one after another, blurred to sharp. */
export function Words({ t, at, text, className, style }: { t: number; at: number; text: string; className?: string; style?: CSSProperties }) {
  const words = text.split(" ");
  return (
    <span className={className} style={style}>
      {words.map((w, i) => {
        const x = out(prog(t, at + i * 0.09, 0.75));
        return (
          <span key={i} style={{ display: "inline-block", opacity: x, filter: `blur(${(1 - x) * 9}px)`, transform: `translateY(${(1 - x) * 16}px)`, marginRight: "0.26em" }}>
            {w}
          </span>
        );
      })}
    </span>
  );
}

/** Typed text with a caret. */
export function Typed({ t, at, text, cps = 18, className }: { t: number; at: number; text: string; cps?: number; className?: string }) {
  const n = Math.max(0, Math.min(text.length, Math.floor((t - at) * cps)));
  const typing = t >= at && n < text.length + 6;
  return (
    <span className={className}>
      {text.slice(0, n)}
      <span style={{ opacity: typing && Math.floor(t * 2.4) % 2 === 0 ? 1 : 0, color: "var(--green)", fontWeight: 300 }}>|</span>
    </span>
  );
}

export type CursorKey = { t: number; x: number; y: number; click?: boolean };

/** A pointer that travels between keyframes and leaves a click ring. */
export function Cursor({ t, keys }: { t: number; keys: CursorKey[] }) {
  let x = keys[0].x, y = keys[0].y;
  for (let i = 1; i < keys.length; i++) {
    const a = keys[i - 1], b = keys[i];
    if (t >= a.t) {
      const k = inOut(prog(t, a.t, b.t - a.t));
      x = lerp(a.x, b.x, k); y = lerp(a.y, b.y, k);
    }
  }
  const visible = clamp01((t - keys[0].t + 0.3) / 0.3) * (1 - prog(t, keys[keys.length - 1].t + 0.6, 0.3));
  const lastClick = [...keys].reverse().find((k) => k.click && t >= k.t);
  const since = lastClick ? t - lastClick.t : 99;
  const press = since < 0.18 ? 0.86 : 1;
  return (
    <div style={{ position: "absolute", left: x, top: y, opacity: visible, pointerEvents: "none", zIndex: 50 }}>
      {since < 0.7 && (
        <span style={{ position: "absolute", left: -22, top: -22, width: 44, height: 44, borderRadius: 99, border: "2px solid var(--green)",
          opacity: 1 - since / 0.7, transform: `scale(${0.4 + since * 1.4})` }} />
      )}
      <svg width="26" height="30" viewBox="0 0 26 30" style={{ transform: `scale(${press})`, transformOrigin: "2px 2px", filter: "drop-shadow(0 4px 6px rgb(0 0 0 / .25))" }}>
        <path d="M2 2l20 11.5-8.6 2.2L9.3 25z" fill="#16201c" stroke="white" strokeWidth="2" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

/** App window chrome, light, used for every product shot. */
export function AppWindow({ title, children, style, className }: { title: string; children: ReactNode; style?: CSSProperties; className?: string }) {
  return (
    <div className={className} style={{ borderRadius: 18, background: "white", border: "1px solid var(--border)", boxShadow: "var(--shadow-float)", overflow: "hidden", ...style }}>
      <div style={{ height: 38, display: "flex", alignItems: "center", gap: 7, padding: "0 16px", borderBottom: "1px solid var(--border)", background: "oklch(0.985 0.002 165)" }}>
        {["#e5e7e6", "#e5e7e6", "#e5e7e6"].map((c, i) => <span key={i} style={{ width: 10, height: 10, borderRadius: 99, background: c }} />)}
        <span style={{ marginLeft: 12, fontSize: 15, color: "var(--muted-foreground)" }}>{title}</span>
      </div>
      <div style={{ position: "relative" }}>{children}</div>
    </div>
  );
}

/** Count up from 0 (or `from`) to `to`, eased. */
export function count(t: number, at: number, to: number, from = 0, dur = 1.2) {
  return Math.round(lerp(from, to, out(prog(t, at, dur))));
}
