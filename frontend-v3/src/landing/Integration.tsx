import { motion } from "motion/react";
import { FileText, CalendarClock, Bus, MessageSquareWarning, Radio, Route, Network, QrCode, Megaphone } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Logo } from "./Logo";

type Node = { icon: LucideIcon; label: string; note: string };

const IN: Node[] = [
  { icon: FileText, label: "Anunțul STPT", note: "stpt.ro" },
  { icon: CalendarClock, label: "Orarul SMTT", note: "GTFS" },
  { icon: Bus, label: "Vehiculele live", note: "datele Primăriei" },
  { icon: MessageSquareWarning, label: "Sesizările", note: "doar numărate" },
];
const OUT: Node[] = [
  { icon: Radio, label: "CityApp și Google", note: "GTFS-RT" },
  { icon: Route, label: "Punctul Național de Acces", note: "DATEX II" },
  { icon: Network, label: "Platforma orașului", note: "NGSI-LD" },
  { icon: QrCode, label: "Afișul din stație", note: "A4, QR și audio" },
  { icon: Megaphone, label: "Anunțuri pe cartiere", note: "text gata de trimis" },
];

// One coordinate system for beams (SVG) and pills (absolutely positioned HTML).
const VW = 1000;
const VH = 440;
const HUB = { x: 500, y: VH / 2 };
const LEFT_X = 210;
const RIGHT_X = 790;
const ys = (n: number) => Array.from({ length: n }, (_, i) => 50 + (i * (VH - 100)) / (n - 1));

const beam = (x0: number, y0: number, x1: number, y1: number) => {
  const mx = (x0 + x1) / 2;
  return `M${x0} ${y0}C${mx} ${y0} ${mx} ${y1} ${x1} ${y1}`;
};

function Pill({ n, x, y, align }: { n: Node; x: number; y: number; align: "left" | "right" }) {
  const Icon = n.icon;
  return (
    <div className="absolute flex -translate-y-1/2 items-center gap-3 rounded-full border bg-card py-2 pl-2 pr-4 shadow-card"
      style={{ top: `${(y / VH) * 100}%`, ...(align === "left" ? { right: `${100 - (x / VW) * 100}%` } : { left: `${(x / VW) * 100}%` }) }}>
      <span className="grid size-8 place-items-center rounded-full bg-muted">
        <Icon className="size-4" strokeWidth={1.8} />
      </span>
      <span className="leading-tight">
        <span className="block whitespace-nowrap text-sm font-medium">{n.label}</span>
        <span className="block whitespace-nowrap text-xs text-muted-foreground">{n.note}</span>
      </span>
    </div>
  );
}

export function Integration() {
  const inY = ys(IN.length);
  const outY = ys(OUT.length);
  const paths = [
    ...inY.map((y, i) => ({ d: beam(LEFT_X, y, HUB.x - 70, HUB.y), delay: i * 0.35 })),
    ...outY.map((y, i) => ({ d: beam(HUB.x + 70, HUB.y, RIGHT_X, y), delay: 1.2 + i * 0.3 })),
  ];
  return (
    <div className="relative mx-auto aspect-[1000/440] w-full max-w-5xl">
      <svg viewBox={`0 0 ${VW} ${VH}`} className="absolute inset-0 h-full w-full" aria-hidden>
        {paths.map((p, i) => (
          <g key={i}>
            <path d={p.d} fill="none" stroke="var(--border)" strokeWidth={1.5} />
            <motion.path d={p.d} fill="none" stroke="var(--green)" strokeWidth={2} strokeLinecap="round" pathLength={1}
              strokeDasharray="0.12 1" initial={{ strokeDashoffset: 0.12 }} animate={{ strokeDashoffset: -1 }}
              transition={{ duration: 2.2, delay: p.delay, repeat: Infinity, repeatDelay: 1.4, ease: [0.45, 0, 0.2, 1] }} />
          </g>
        ))}
      </svg>
      {IN.map((n, i) => <Pill key={n.label} n={n} x={LEFT_X} y={inY[i]} align="left" />)}
      {OUT.map((n, i) => <Pill key={n.label} n={n} x={RIGHT_X} y={outY[i]} align="right" />)}
      <div className="absolute left-1/2 top-1/2 grid size-36 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-[2rem] border bg-card shadow-float">
        <div className="flex flex-col items-center gap-2">
          <Logo className="size-11" />
          <span className="text-sm font-semibold tracking-tight">Rețeaua Vie</span>
        </div>
      </div>
    </div>
  );
}
