import { cn } from "@/lib/utils";
import { count, type LineReliability } from "./data";

/** Trips seen in the live data against trips in the timetable: the seen part in ink, the unseen part in red. */
export function SeenBar({ t, className }: { t: LineReliability["trips"]; className?: string }) {
  const share = t.scheduled ? t.observed / t.scheduled : 1;
  return (
    <span className={cn("block h-1.5 overflow-hidden rounded-full", t.missed > 0 ? "bg-closure/35" : "bg-muted", className)} aria-hidden>
      <span className={cn("block h-full rounded-full", t.missed > 0 ? "bg-foreground" : "bg-foreground/30")} style={{ width: `${Math.max(share * 100, share > 0 ? 3 : 0)}%` }} />
    </span>
  );
}

/**
 * The line's day, hour by hour: the outline is the timetable, the fill is what the live data showed.
 * An empty outline is an hour with trips on paper and no vehicle seen.
 */
export function HourBars({ hours }: { hours: LineReliability["hours"] }) {
  const rows = hours.filter((h) => h.trips.scheduled > 0 || h.trips.observed > 0);
  const max = Math.max(1, ...rows.map((h) => Math.max(h.trips.scheduled, h.trips.observed)));
  if (!rows.length) return null;
  return (
    <figure>
      <div className="flex h-20 items-end gap-[3px]" role="img"
        aria-label={`Curse pe oră: ${rows.map((h) => `ora ${h.hour}, ${h.trips.observed} văzute din ${h.trips.scheduled}`).join("; ")}`}>
        {rows.map((h) => (
          <div key={h.hour} className="relative flex h-full flex-1 items-end" title={`${String(h.hour).padStart(2, "0")}:00 · ${h.trips.observed} văzute din ${count(h.trips.scheduled, "cursă", "curse")} din orar`}>
            <div className="w-full rounded-[3px] border border-closure/50 bg-closure-soft" style={{ height: `${(h.trips.scheduled / max) * 100}%`, minHeight: 3 }} />
            <div className="absolute inset-x-0 bottom-0 rounded-[3px] bg-foreground" style={{ height: `${(Math.min(h.trips.observed, h.trips.scheduled) / max) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className="tabular mt-1 flex gap-[3px] text-[0.6875rem] text-muted-foreground" aria-hidden>
        {rows.map((h, i) => <span key={h.hour} className="flex-1 text-center">{i % 2 === 0 ? String(h.hour).padStart(2, "0") : ""}</span>)}
      </div>
      <figcaption className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-[3px] bg-foreground" />văzute în datele live</span>
        <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-[3px] border border-closure/50 bg-closure-soft" />în orar, nevăzute</span>
      </figcaption>
    </figure>
  );
}

/** Punctuality in four classes, as one bar with its words. */
export function PunctualityBar({ p }: { p: LineReliability["punctuality"] }) {
  const parts: [string, number, string][] = [
    ["devansat", p.early ?? 0, "bg-foreground/35"],
    ["la timp", p.onTime ?? 0, "bg-primary"],
    ["întârziat", p.late ?? 0, "bg-closure/60"],
    ["foarte întârziat", p.veryLate ?? 0, "bg-closure"],
  ];
  const pct = (x: number) => `${Math.round(x * 100)} %`;
  return (
    <div>
      <div className="flex h-2 gap-px overflow-hidden rounded-full" aria-hidden>
        {parts.filter(([, v]) => v > 0).map(([k, v, c]) => <span key={k} className={c} style={{ width: `${v * 100}%` }} />)}
      </div>
      <p className="tabular mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-sm text-foreground/80">
        {parts.filter(([, v]) => v >= 0.005).map(([k, v]) => <span key={k}>{k} {pct(v)}</span>)}
      </p>
    </div>
  );
}
