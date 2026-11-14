import type { CSSProperties, ReactNode } from "react";
import { Check, FileText, CalendarClock, Bus, Radio, Route, QrCode, Network, MapPinned, ListChecks, Send, Eye, FileBarChart, LayoutGrid } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Logo } from "@/landing/Logo";
import { LineBadge } from "@/landing/LineBadge";
import { fmt, hhmm } from "@/lib/api";
import type { FilmData, Geo } from "./data";
import { AppWindow, Cursor, Words, count, inOut, lerp, out, prog, reveal } from "./kit";

export type SceneProps = { t: number; d: FilmData; g: Geo };
export type Scene = { id: string; dur: number; render: (p: SceneProps) => ReactNode };

const center: CSSProperties = { position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" };
const headline: CSSProperties = { fontSize: 64, fontWeight: 680, letterSpacing: "-0.035em", lineHeight: 1.05, color: "var(--foreground)" };
const title: CSSProperties = { position: "absolute", top: 46, left: 0, right: 0, textAlign: "center", fontSize: 40, fontWeight: 660, letterSpacing: "-0.03em" };

const dayTime = (iso: string) =>
  new Date(iso).toLocaleString("ro-RO", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Bucharest" });

/* ---------- 1. Hook: the evidence ---------- */
/** The opening lines of the real STPT notice, sharp. Also the film's still frame before the data arrives (text = null: placeholder lines). */
export function Notice({ text, style }: { text: string | null; style?: CSSProperties }) {
  const lines = (text ?? "").split("\n").filter(Boolean).slice(0, 3);
  return (
    <div style={{ position: "absolute", left: 80, top: 96, width: 540, background: "white", border: "1px solid var(--border)", borderRadius: 18, padding: "26px 30px", boxShadow: "var(--shadow-float)", textAlign: "left", ...style }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 16, color: "var(--muted-foreground)" }}>
        <FileText size={18} strokeWidth={1.8} /> Anunțul STPT, de pe stpt.ro
      </div>
      {text
        ? lines.map((l, i) => (
            <p key={i} style={{ marginTop: i ? 12 : 16, fontSize: i ? 16 : 19, lineHeight: 1.45, color: i ? "var(--muted-foreground)" : "var(--foreground)", fontWeight: i ? 400 : 500,
              display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: i ? 3 : 8, overflow: "hidden" }}>{l}</p>
          ))
        : [470, 440, 478, 300, 450, 380].map((w, i) => <div key={i} style={{ height: 12, width: w, borderRadius: 9, background: "var(--muted)", marginTop: i ? 14 : 22 }} />)}
    </div>
  );
}

function Hook({ t, d, g }: SceneProps) {
  const base = d.impact.totals.departuresLost;
  const best = d.windows.candidates[0];
  const dropAt = 7.4;
  const picked = !!best && t >= dropAt;
  const n = picked ? count(t, dropAt, best.departuresLost, base, 1.2) : count(t, 4.4, base, 0, 1.8);
  const mapScale = 520 / WIN.mapW;
  return (
    <>
      <Notice text={d.closure.sourceText ?? d.closure.title.ro} style={{ opacity: out(prog(t, 0, 0.5)) }} />
      <div style={{ position: "absolute", left: 680, top: 96, width: 520, height: WIN.mapH * mapScale, borderRadius: 18, overflow: "hidden", border: "1px solid var(--border)", boxShadow: "var(--shadow-card)", ...reveal(t, 2.2) }}>
        <div style={{ transform: `scale(${mapScale})`, transformOrigin: "0 0" }}><PlanMap t={t} g={g} drawAt={2.8} /></div>
      </div>
      <div style={{ position: "absolute", left: 680, top: 96 + WIN.mapH * mapScale + 30, width: 520, textAlign: "left", ...reveal(t, 4.2) }}>
        <div className="tabular" style={{ fontSize: 96, fontWeight: 680, letterSpacing: "-0.04em", lineHeight: 1, color: picked ? "var(--primary)" : "var(--closure-ink)" }}>{fmt.format(n)}</div>
        <div style={{ marginTop: 10, fontSize: 21, color: "var(--muted-foreground)" }}>plecări pierdute, estimare pe orarul SMTT</div>
        {best && (
          <div className="tabular" style={{ marginTop: 14, fontSize: 19, fontWeight: 550, ...reveal(t, dropAt - 0.6) }}>
            Fereastra propusă: {dayTime(best.window.start)} – {dayTime(best.window.end)}
          </div>
        )}
      </div>
    </>
  );
}

/* ---------- 2. Reveal ---------- */
function Reveal({ t }: SceneProps) {
  const a = out(prog(t, 0.1, 0.9));
  return (
    <div style={center}>
      <div style={{ display: "flex", alignItems: "center", gap: 22, transform: `scale(${lerp(0.9, 1, a)})`, opacity: a, filter: `blur(${(1 - a) * 10}px)` }}>
        <Logo className="size-20" />
        <span style={{ ...headline, fontSize: 84 }}>Rețeaua Vie</span>
      </div>
      <div style={{ marginTop: 26, padding: "10px 20px", borderRadius: 99, background: "white", border: "1px solid var(--border)", boxShadow: "var(--shadow-card)", fontSize: 20, ...reveal(t, 0.9) }}>
        Biroul de mobilitate pentru lucrările de pe străzi
      </div>
    </div>
  );
}

/* ---------- 3–5. Plan: draw, impact, window (one continuous product shot) ---------- */
const WIN = { x: 100, y: 128, w: 1080, side: 260, mapW: 820, mapH: 522, bar: 38 };

function StepList({ active }: { active: number }) {
  const steps: [LucideIcon, string][] = [[LayoutGrid, "Ansamblu"], [MapPinned, "Planifici"], [ListChecks, "Decizi"], [Send, "Publici"], [Eye, "Urmărești"], [FileBarChart, "Raportezi"]];
  return (
    <div style={{ width: WIN.side, padding: 18, borderRight: "1px solid var(--border)", height: WIN.mapH, background: "oklch(0.99 0.002 165)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 22 }}>
        <Logo className="size-7" /><span style={{ fontWeight: 650, fontSize: 15 }}>Rețeaua Vie</span>
      </div>
      {steps.map(([Icon, s], i) => (
        <div key={s} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 10px", borderRadius: 10, fontSize: 14, marginBottom: 2,
          background: i === active ? "var(--accent)" : "transparent", color: i === active ? "var(--accent-foreground)" : "var(--muted-foreground)", fontWeight: i === active ? 600 : 450 }}>
          <Icon size={16} strokeWidth={1.8} />{s}
        </div>
      ))}
    </div>
  );
}

function PlanMap({ t, g, drawAt }: { t: number; g: Geo; drawAt: number }) {
  const { crop } = g;
  const z = lerp(1, 0.94, inOut(prog(t, 0, 20))); // slow camera push
  const vb = { w: crop.w * z, h: crop.h * z };
  const vx = crop.x + (crop.w - vb.w) / 2, vy = crop.y + (crop.h - vb.h) / 2;
  const seg = "M" + g.seg.map(([x, y]) => `${x.toFixed(2)} ${y.toFixed(2)}`).join("L");
  const k = out(prog(t, drawAt, 1.1));
  return (
    <svg width={WIN.mapW} height={WIN.mapH} viewBox={`${vx} ${vy} ${vb.w} ${vb.h}`} style={{ display: "block", background: "white" }}>
      <path d={g.cropDots} fill="var(--dot)" />
      <path d={g.streets} fill="none" stroke="oklch(0.9 0.006 165)" strokeWidth={0.6} strokeLinecap="round" strokeLinejoin="round" />
      <g fill="none" strokeLinecap="round" strokeLinejoin="round">
        {g.lines.map((l) => (
          <path key={l.id} d={l.d} stroke={l.affected ? l.color : "oklch(0.8 0.01 165)"} strokeWidth={l.affected ? 1.1 : 0.55} opacity={l.affected ? 0.95 : 0.7} />
        ))}
      </g>
      <path d={seg} fill="none" stroke="var(--closure)" strokeOpacity={0.25} strokeWidth={4.5 * k} strokeLinecap="round" />
      <path d={seg} fill="none" stroke="var(--closure)" strokeWidth={1.8} strokeLinecap="round" pathLength={1} strokeDasharray={`${k} 1`} />
    </svg>
  );
}

/** Canvas position of a point given in projected map units. */
function toCanvas(g: Geo, [x, y]: [number, number]) {
  return { x: WIN.x + WIN.side + ((x - g.crop.x) / g.crop.w) * WIN.mapW, y: WIN.y + WIN.bar + ((y - g.crop.y) / g.crop.h) * WIN.mapH };
}

function Panel({ t, at, children, width = 330 }: { t: number; at: number; children: ReactNode; width?: number }) {
  const a = out(prog(t, at, 0.8));
  return (
    <div style={{ position: "absolute", right: 22, top: 22, width, padding: 20, borderRadius: 16, background: "white", border: "1px solid var(--border)",
      boxShadow: "var(--shadow-float)", opacity: a, transform: `translateX(${(1 - a) * 40}px)`, filter: `blur(${(1 - a) * 6}px)` }}>
      {children}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone: "closure" | "muted" | "green" }) {
  const bg = tone === "closure" ? "var(--closure-soft)" : tone === "green" ? "var(--green-soft)" : "var(--muted)";
  const fg = tone === "closure" ? "var(--closure-ink)" : tone === "green" ? "var(--accent-foreground)" : "var(--muted-foreground)";
  return (
    <div style={{ background: bg, borderRadius: 12, padding: "10px 14px" }}>
      <div style={{ fontSize: 15, color: fg }}>{label}</div>
      <div className="tabular" style={{ fontSize: 30, fontWeight: 650, letterSpacing: "-0.03em" }}>{value}</div>
    </div>
  );
}

/** The plan shot keeps its own 20 s clock; on screen its two holds (4.6–7.4 and 10–13) run faster, so it takes 17 s. */
function planTime(t: number) {
  if (t < 4.6) return t;
  if (t < 5.4) return lerp(4.6, 7.4, (t - 4.6) / 0.8);
  if (t < 8) return t + 2;
  if (t < 10) return lerp(10, 13, (t - 8) / 2);
  return t + 3;
}

function Plan({ t, d, g }: SceneProps) {
  // phases (local seconds): draw 0–7, impact 7–14, window 14–20
  const tilt = inOut(prog(t, 0, 1.6));
  const A = toCanvas(g, g.seg[0]);
  const B = toCanvas(g, g.seg[g.seg.length - 1]);
  const base = d.windows.baselineDeparturesLost;
  const best = d.windows.candidates[0];
  const picked = t >= 17.2;
  const lost = picked ? count(t, 17.3, best.departuresLost, base, 1.1) : count(t, 8.2, d.impact.totals.departuresLost, 0, 1.4);

  return (
    <>
      <div style={{ ...title, ...reveal(t, 0.2, 6.6) }}>Trasezi lucrarea pe hartă.</div>
      <div style={{ ...title, ...reveal(t, 7, 13.6) }}>Vezi cine pierde serviciul.</div>
      <div style={{ ...title, ...reveal(t, 14, 19.6) }}>Alegi fereastra care face mai puțin rău.</div>

      <div style={{ position: "absolute", inset: 0, transformOrigin: "1160px 196px",
        transform: `scale(${1 + 0.24 * (inOut(prog(t, 7.6, 1)) * (1 - inOut(prog(t, 13.4, 0.7))) + inOut(prog(t, 14.6, 1)) * (1 - inOut(prog(t, 19.2, 0.6))))})` }}>
      <div style={{ position: "absolute", left: WIN.x, top: WIN.y, perspective: 1800 }}>
        <AppWindow title="Planifici · lucrare nouă" style={{ width: WIN.w, opacity: out(prog(t, 0, 0.8)),
          transform: `rotateX(${lerp(16, 0, tilt)}deg) rotateY(${lerp(-14, 0, tilt)}deg) scale(${lerp(0.9, 1, tilt)})`, transformOrigin: "50% 0" }}>
          <div style={{ display: "flex" }}>
            <StepList active={t < 14 ? 1 : 2} />
            <div style={{ position: "relative" }}>
              <PlanMap t={t} g={g} drawAt={3.5} />
              <div style={{ position: "absolute", left: 22, bottom: 22, padding: "8px 12px", borderRadius: 10, background: "white", border: "1px solid var(--border)",
                fontSize: 15, boxShadow: "var(--shadow-card)", ...reveal(t, 4.6, 7) }}>
                {d.closure.title.ro}
              </div>
              {t >= 7 && t < 14.2 && (
                <Panel t={t} at={7.3}>
                  <div style={{ display: "flex", gap: 6 }}>{d.closure.routeIds.map((r) => <LineBadge key={r} routeId={r} size="lg" />)}</div>
                  <div style={{ fontSize: 14, fontWeight: 550, margin: "12px 0 14px", lineHeight: 1.35 }}>{d.closure.title.ro}</div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    <Stat label="Plecări pierdute" value={fmt.format(lost)} tone="closure" />
                    <Stat label="Stații suspendate" value={fmt.format(count(t, 8.6, d.impact.totals.stopsSuspended, 0, 0.8))} tone="muted" />
                  </div>
                  <div style={{ fontSize: 15, color: "var(--muted-foreground)", marginTop: 12 }}>Estimare pe orarul planificat SMTT</div>
                </Panel>
              )}
              {t >= 14 && (
                <Panel t={t} at={14.2} width={380}>
                  <Stat label="Plecări pierdute" value={fmt.format(t < 17.2 ? base : lost)} tone={picked ? "green" : "closure"} />
                  {[
                    { label: "Fereastra din anunț", when: `${dayTime(d.impact.window.start)} – ${hhmm(d.impact.window.end)}`, n: base, on: !picked },
                    { label: "Fereastra propusă", when: `${dayTime(best.window.start)} – ${hhmm(best.window.end)}`, n: best.departuresLost, on: picked },
                  ].map((r) => (
                    <div key={r.label} style={{ marginTop: 12, padding: 12, borderRadius: 12, border: r.on ? "2px solid var(--green)" : "1px solid var(--border)", background: "white" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 15 }}>
                        <span style={{ fontWeight: 600 }}>{r.label}</span><span className="tabular">{fmt.format(r.n)} plecări</span>
                      </div>
                      <div className="tabular" style={{ fontSize: 15, color: "var(--muted-foreground)", marginTop: 3 }}>{r.when}</div>
                    </div>
                  ))}
                  <div style={{ fontSize: 15, color: "var(--muted-foreground)", marginTop: 12 }}>Estimare pe orarul planificat SMTT</div>
                </Panel>
              )}
            </div>
          </div>
        </AppWindow>
      </div>

      <Cursor t={t} keys={[
        { t: 1.6, x: 760, y: 560 }, { t: 2.4, x: A.x, y: A.y, click: true }, { t: 3.4, x: B.x, y: B.y, click: true }, { t: 4.4, x: B.x + 60, y: B.y + 70 },
        { t: 15.6, x: 900, y: 560 }, { t: 17.0, x: 1010, y: 420, click: true }, { t: 18.6, x: 1060, y: 470 },
      ]} />
      </div>
    </>
  );
}

/* ---------- 6. Publish: in → Rețeaua Vie → out ---------- */
type Node = [LucideIcon, string, string];
const IN: Node[] = [[FileText, "Anunțul STPT", "stpt.ro"], [CalendarClock, "Orarul SMTT", "GTFS"], [Bus, "Vehiculele live", "datele Primăriei"]];
const OUT: Node[] = [[Radio, "CityApp și Google", "GTFS-RT"], [Route, "Punctul Național de Acces", "DATEX II"], [Network, "Platforma orașului", "NGSI-LD"], [QrCode, "Afișul din stație", "QR și audio"]];
const HUB = { x: 640, y: 420 };

function Node({ n, x, y, align, style }: { n: Node; x: number; y: number; align: "l" | "r"; style: CSSProperties }) {
  const [Icon, label, note] = n;
  return (
    <div style={{ position: "absolute", top: y - 28, ...(align === "l" ? { right: 1280 - x } : { left: x }), display: "flex", alignItems: "center", gap: 12,
      padding: "8px 18px 8px 8px", borderRadius: 99, background: "white", border: "1px solid var(--border)", boxShadow: "var(--shadow-card)", ...style }}>
      <span style={{ width: 40, height: 40, borderRadius: 99, background: "var(--muted)", display: "grid", placeItems: "center" }}><Icon size={19} strokeWidth={1.8} /></span>
      <span style={{ lineHeight: 1.2 }}><span style={{ display: "block", fontSize: 16, fontWeight: 560 }}>{label}</span><span style={{ fontSize: 15, color: "var(--muted-foreground)" }}>{note}</span></span>
    </div>
  );
}

function Publish({ t }: SceneProps) {
  const clickAt = 1.6;
  const morph = out(prog(t, clickAt, 0.7));
  const inY = IN.map((_, i) => 290 + i * 130);
  const outY = OUT.map((_, i) => 250 + i * 112);
  const curve = (x0: number, y0: number, x1: number, y1: number) => `M${x0} ${y0}C${(x0 + x1) / 2} ${y0} ${(x0 + x1) / 2} ${y1} ${x1} ${y1}`;
  return (
    <>
      <div style={{ ...title, ...reveal(t, 0.2) }}><Words t={t} at={0.2} text="Publici o dată. Ajunge peste tot." /></div>
      <svg width={1280} height={720} style={{ position: "absolute", inset: 0 }}>
        {inY.map((y, i) => {
          const k = out(prog(t, 0.6 + i * 0.15, 0.9));
          const d = curve(300, y, HUB.x - 90, HUB.y);
          const flow = (t * 0.55 + i * 0.3) % 1;
          return (
            <g key={`i${i}`} opacity={k}>
              <path d={d} fill="none" stroke="var(--border)" strokeWidth={2} />
              <path d={d} fill="none" stroke="var(--green)" strokeWidth={2.5} strokeLinecap="round" pathLength={1} strokeDasharray="0.1 1" strokeDashoffset={0.1 - flow * 1.1} />
            </g>
          );
        })}
        {outY.map((y, i) => {
          const k = out(prog(t, clickAt + 0.5 + i * 0.35, 1));
          const d = curve(HUB.x + 90, HUB.y, 940, y);
          return (
            <g key={`o${i}`}>
              <path d={d} fill="none" stroke="var(--border)" strokeWidth={2} opacity={k} />
              <path d={d} fill="none" stroke="var(--green)" strokeWidth={2.5} strokeLinecap="round" pathLength={1} strokeDasharray={`${k} 1`} />
            </g>
          );
        })}
      </svg>
      {IN.map((n, i) => <Node key={n[1]} n={n} x={300} y={inY[i]} align="l" style={reveal(t, 0.5 + i * 0.15)} />)}
      {OUT.map((n, i) => <Node key={n[1]} n={n} x={940} y={outY[i]} align="r" style={reveal(t, clickAt + 1.2 + i * 0.35)} />)}
      <div style={{ position: "absolute", left: HUB.x, top: HUB.y, transform: "translate(-50%, -50%)", display: "grid", placeItems: "center",
        width: lerp(170, 180, morph), height: lerp(64, 180, morph), borderRadius: lerp(99, 40, morph),
        background: lerp(0, 1, morph) > 0.5 ? "white" : "var(--primary)", border: "1px solid var(--border)", boxShadow: "var(--shadow-float)",
        opacity: out(prog(t, 0.3, 0.6)) }}>
        {morph < 0.5 ? (
          <span style={{ color: "white", fontSize: 22, fontWeight: 600, display: "flex", gap: 10, alignItems: "center", opacity: 1 - morph * 2 }}><Send size={20} />Publică</span>
        ) : (
          <span style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10, opacity: morph * 2 - 1 }}>
            <Logo className="size-14" /><span style={{ fontSize: 17, fontWeight: 650 }}>Rețeaua Vie</span>
          </span>
        )}
      </div>
      <Cursor t={t} keys={[{ t: 0.6, x: 760, y: 620 }, { t: clickAt, x: HUB.x + 20, y: HUB.y + 8, click: true }, { t: 2.6, x: HUB.x + 140, y: HUB.y + 160 }]} />
    </>
  );
}

/* ---------- 7. Monitor ---------- */
function Monitor({ t, d, g }: SceneProps) {
  const miss = d.missing.find((r) => r.state === "fara_vehicul");
  const confirmAt = 3.1;
  const done = t >= confirmAt;
  const s = 600 / g.p.width;
  return (
    <>
      <div style={{ ...title, ...reveal(t, 0.2) }}><Words t={t} at={0.2} text="Urmărești ce s-a întâmplat de fapt." /></div>
      <div style={{ position: "absolute", left: 90, top: 140, ...reveal(t, 0.3) }}>
        <svg width={600} height={g.p.height * s} viewBox={`0 0 ${g.p.width} ${g.p.height}`}>
          <path d={g.cityDots} fill="var(--dot-strong)" opacity={0.42} />
          <g fill="none" strokeLinecap="round" strokeLinejoin="round" opacity={out(prog(t, 0.3, 0.8)) * 0.65}>
            {g.lines.map((l) => <path key={l.id} d={l.d} stroke={l.color} strokeWidth={l.tram ? 3 : 2} />)}
          </g>
          {g.vehicles.map((v, i) => (
            <circle key={v.id} cx={v.x} cy={v.y} r={4.6} fill="var(--foreground)" stroke="white" strokeWidth={1.8} opacity={out(prog(t, 0.6 + (i % 20) * 0.04, 0.5))} />
          ))}
        </svg>
        <div className="tabular" style={{ fontSize: 15, color: "var(--muted-foreground)", marginTop: 6 }}>
          {fmt.format(g.vehicles.length)} vehicule în datele live ale Primăriei, înregistrate de noi
        </div>
      </div>
      <div style={{ position: "absolute", left: 720, top: 250, width: 500, ...reveal(t, 1.0) }}>
        {miss ? (
          <div style={{ background: "white", border: done ? "2px solid var(--green)" : "1px solid var(--border)", borderRadius: 18, padding: 18, boxShadow: "var(--shadow-float)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <LineBadge routeId={miss.routeId} label={miss.shortName} size="lg" />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 18, fontWeight: 600 }}>{miss.longName}</div>
                <div className="tabular" style={{ fontSize: 15, color: "var(--muted-foreground)" }}>
                  Fără vehicul în datele live · {miss.tripsObserved} din {miss.tripsInService} curse văzute
                </div>
              </div>
            </div>
            <div style={{ marginTop: 16, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ fontSize: 15, maxWidth: 300, color: done ? "var(--accent-foreground)" : "var(--muted-foreground)" }}>
                {done ? "Confirmat de dispecer. Semnalul e gata pentru CityApp." : "Un om confirmă înainte de CityApp."}
              </span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "8px 14px", borderRadius: 10, fontSize: 14, fontWeight: 600,
                background: done ? "var(--green-soft)" : "var(--primary)", color: done ? "var(--accent-foreground)" : "white" }}>
                <Check size={16} />{done ? "Confirmat" : "Confirmă"}
              </span>
            </div>
          </div>
        ) : (
          <div style={{ background: "white", border: "1px solid var(--border)", borderRadius: 18, padding: 18, fontSize: 16 }}>Toate liniile din orar au vehicule în datele live acum.</div>
        )}
      </div>
      {miss && <Cursor t={t} keys={[{ t: 1.8, x: 1000, y: 560 }, { t: confirmAt, x: 1150, y: 372, click: true }, { t: 4.4, x: 1180, y: 450 }]} />}
    </>
  );
}

/* ---------- 8. Outro ---------- */
function Outro({ t }: SceneProps) {
  const lines = ["Mai puțin timp pierdut.", "Călători informați.", "Dovezi la zi."];
  return (
    <>
      {lines.map((l, i) => (
        <div key={l} style={{ ...center, ...headline, fontSize: 60, ...reveal(t, i * 1.1, i < 2 ? (i + 1) * 1.1 - 0.15 : 3.4) }}>{l}</div>
      ))}
      <div style={center}>
        <div style={{ display: "flex", alignItems: "center", gap: 18, ...reveal(t, 3.8) }}>
          <Logo className="size-16" /><span style={{ ...headline, fontSize: 64 }}>Rețeaua Vie</span>
        </div>
        <div style={{ marginTop: 22, padding: "9px 18px", borderRadius: 99, background: "var(--foreground)", color: "white", fontSize: 17, ...reveal(t, 4.2) }}>
          unihack.alberyt.xyz
        </div>
      </div>
    </>
  );
}

export const SCENES: Scene[] = [
  { id: "hook", dur: 10, render: Hook },
  { id: "reveal", dur: 3, render: Reveal },
  { id: "plan", dur: 17, render: (p) => Plan({ ...p, t: planTime(p.t) }) },
  { id: "publish", dur: 7, render: Publish },
  { id: "monitor", dur: 5.5, render: Monitor },
  { id: "outro", dur: 5.5, render: Outro },
];
export const TOTAL = SCENES.reduce((s, x) => s + x.dur, 0);
