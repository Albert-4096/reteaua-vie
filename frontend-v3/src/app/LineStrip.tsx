import { Fragment, useMemo, useState, type ReactNode } from "react";
import { ChevronDown, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { count } from "./data";
import type { Station } from "./lines";

export type Mark = "closed" | "ask" | "served" | "plain";
export type StripRow = { station: Station; mark: Mark; chips?: ReactNode };

const WORD: Record<Mark, string> = { closed: "nu oprește", ask: "de hotărât", served: "oprește", plain: "" };

/** How the line is drawn between two neighbouring stations. */
function link(a: Mark | undefined, b: Mark | undefined, color: string): React.CSSProperties | null {
  if (!a || !b) return null;
  if (a === "closed" && b === "closed") return { backgroundImage: "repeating-linear-gradient(var(--closure) 0 4px, transparent 4px 8px)" };
  if (a === "ask" && b === "ask") return { backgroundImage: "repeating-linear-gradient(var(--foreground) 0 4px, transparent 4px 8px)" };
  return { background: color };
}

function Dot({ mark, end, color }: { mark: Mark; end: boolean; color: string }) {
  if (mark === "closed") return <span className="grid size-[15px] place-items-center rounded-full bg-closure text-white ring-2 ring-card"><X className="size-2.5" strokeWidth={3.5} /></span>;
  if (mark === "ask") return <span className="grid size-[15px] place-items-center rounded-full border-[2.5px] border-foreground bg-card ring-2 ring-card"><span className="size-1 rounded-full bg-foreground" /></span>;
  if (end) return <span className="block size-[15px] rounded-full border-[3.5px] bg-card ring-2 ring-card" style={{ borderColor: color }} />;
  if (mark === "served") return <span className="block size-[11px] rounded-full border-[2.5px] bg-card ring-2 ring-card" style={{ borderColor: color }} />;
  return <span className="block size-[9px] rounded-full ring-2 ring-card" style={{ background: color }} />;
}

/**
 * A line as the vehicle travels it: every station in order, on a track in the line's own colour.
 * Stations where it does not stop carry a red cross, the ones a person still has to decide a ring.
 * Long runs of the same kind fold into "N stații" so the shape of the line stays readable.
 */
export function LineStrip({ color, rows, fold = true, onHover, className }: { color: string; rows: StripRow[]; fold?: boolean; onHover?: (s: Station | null) => void; className?: string }) {
  const [open, setOpen] = useState<Set<number>>(new Set());

  // runs of neighbouring stations with the same mark: [start, end] inclusive
  const runs = useMemo(() => {
    const out: [number, number][] = [];
    rows.forEach((r, i) => {
      const last = out[out.length - 1];
      if (last && rows[last[0]].mark === r.mark) last[1] = i;
      else out.push([i, i]);
    });
    return out;
  }, [rows]);

  const row = (i: number, firstOfRun: boolean) => {
    const r = rows[i];
    const end = i === 0 || i === rows.length - 1;
    const up = link(rows[i - 1]?.mark, r.mark, color), down = link(r.mark, rows[i + 1]?.mark, color);
    return (
      <li key={r.station.name + i} className="relative grid min-h-8 grid-cols-[1.5rem_minmax(0,1fr)_auto] items-center gap-x-2.5"
        onPointerEnter={() => onHover?.(r.station)} onPointerLeave={() => onHover?.(null)}>
        <span className="relative grid h-full place-items-center" aria-hidden>
          {up && <span className="absolute bottom-1/2 left-1/2 top-0 w-[3px] -translate-x-1/2" style={up} />}
          {down && <span className="absolute bottom-0 left-1/2 top-1/2 w-[3px] -translate-x-1/2" style={down} />}
          <span className="relative block"><Dot mark={r.mark} end={end} color={color} /></span>
        </span>
        <span className={cn("py-1 text-sm leading-snug", end && "font-semibold", r.mark === "plain" && !end && "text-foreground/70")}>
          {r.station.name}
          {r.mark !== "plain" && <span className="sr-only">, {WORD[r.mark]}</span>}
        </span>
        <span className="flex items-center gap-1.5">
          {r.chips}
          {firstOfRun && r.mark !== "plain" && (
            <span aria-hidden className={cn("whitespace-nowrap text-xs font-medium", r.mark === "closed" ? "text-closure-ink" : r.mark === "ask" ? "text-foreground" : "text-muted-foreground")}>{WORD[r.mark]}</span>
          )}
        </span>
      </li>
    );
  };

  return (
    <ol className={cn("select-none", className)}>
      {runs.map(([a, b], k) => {
        const hidden = b - a - 1; // stations between the first and the last of the run
        if (!fold || hidden < 2 || open.has(k)) return <Fragment key={k}>{Array.from({ length: b - a + 1 }, (_, j) => row(a + j, j === 0))}</Fragment>;
        const style = link(rows[a].mark, rows[a].mark, color)!;
        return (
          <Fragment key={k}>
            {row(a, true)}
            <li className="relative grid min-h-7 grid-cols-[1.5rem_minmax(0,1fr)] items-center gap-x-2.5">
              <span className="relative h-full" aria-hidden><span className="absolute inset-y-0 left-1/2 w-[3px] -translate-x-1/2" style={style} /></span>
              <button type="button" onClick={() => setOpen((s) => new Set(s).add(k))}
                className="-ml-1.5 inline-flex w-fit items-center gap-1 rounded-md px-1.5 py-1 text-xs text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
                {count(hidden, "stație", "stații")} între ele <ChevronDown className="size-3.5" />
              </button>
            </li>
            {row(b, false)}
          </Fragment>
        );
      })}
    </ol>
  );
}
