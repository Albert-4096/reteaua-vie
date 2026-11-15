import { createContext, useContext, useEffect, useRef, type ReactNode } from "react";
import { animate as animeAnimate } from "animejs";
import { CircleCheck } from "lucide-react";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { fmt } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { MapProps } from "./MapView";

/* ---------- the shared map: the open page tells it what to show ---------- */
export type Layers = Omit<MapProps, "onClosure" | "onVehicle">;
export const MapCtx = createContext<(l: Layers) => void>(() => {});
/** A place over the map for a control that belongs to the open page (the replay bar). */
export const MapSlotCtx = createContext<HTMLElement | null>(null);
export function useMapLayers(l: Layers) {
  const set = useContext(MapCtx);
  useEffect(() => set(l), [set, l]);
}

/** The panel beside the map: a fixed head that says where you are, a body that scrolls, one action at the foot. */
export function Panel({ head, children, foot }: { head?: ReactNode; children: ReactNode; foot?: ReactNode }) {
  return (
    <div className="flex h-full flex-col">
      {head && <header className="shrink-0 border-b px-6 pb-4 pt-5">{head}</header>}
      {/* focusable, so the keyboard can scroll it even when it holds no link or button */}
      <div tabIndex={0} role="region" aria-label="Conținutul panoului" className="min-h-0 flex-1 overflow-y-auto px-6 pb-12 pt-5 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/60">{children}</div>
      {foot && <footer className="shrink-0 border-t bg-card px-6 py-4">{foot}</footer>}
    </div>
  );
}

export function Title({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  return (
    <div>
      <h1 className="text-xl font-semibold leading-tight tracking-tight">{children}</h1>
      {sub && <p className="mt-1 text-sm leading-snug text-muted-foreground">{sub}</p>}
    </div>
  );
}

/** A titled group inside a panel. More air above the title than below it. */
export function Section({ title, aside, children, className }: { title: ReactNode; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("mt-8 first:mt-0", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        {aside != null && <span className="tabular text-sm text-muted-foreground">{aside}</span>}
      </div>
      <div className="mt-3">{children}</div>
    </section>
  );
}

/** A number with its name; an estimate says so. */
export function Stat({ value, label, note, tone }: { value: ReactNode; label: string; note?: string; tone?: "closure" | "green" }) {
  return (
    <div>
      <dd className={cn("tabular text-2xl font-semibold leading-none tracking-tight", tone === "closure" && "text-closure-ink", tone === "green" && "text-accent-foreground")}>{value}</dd>
      <dt className="mt-1.5 text-sm leading-snug text-foreground/80">{label}</dt>
      {note && <p className="mt-0.5 text-xs leading-snug text-muted-foreground">{note}</p>}
    </div>
  );
}

/** Details that wait until asked for. */
export function Folds({ children, className, onChange }: { children: ReactNode; className?: string; onChange?: (open: string[]) => void }) {
  return <Accordion type="multiple" onValueChange={onChange} className={cn("mt-8 border-t", className)}>{children}</Accordion>;
}
export function Fold({ id, title, aside, children }: { id: string; title: ReactNode; aside?: ReactNode; children: ReactNode }) {
  return (
    <AccordionItem value={id}>
      <AccordionTrigger className="items-center py-3.5 text-sm hover:no-underline">
        <span className="flex flex-1 items-baseline justify-between gap-3">
          <span>{title}</span>
          {aside != null && <span className="tabular text-sm font-normal text-muted-foreground">{aside}</span>}
        </span>
      </AccordionTrigger>
      <AccordionContent className="pb-5 text-sm">{children}</AccordionContent>
    </AccordionItem>
  );
}

/**
 * Measured and estimated never look alike: a measurement is a solid ink pill with a check and its sample,
 * an estimate a dashed outline that names its model.
 */
export function Kind({ k, detail }: { k: "measured" | "estimate"; detail?: string }) {
  return k === "measured" ? (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-foreground px-2.5 py-1 text-xs font-medium leading-snug text-background">
      <CircleCheck className="size-3.5" /> Măsurat{detail ? ` · ${detail}` : ""}
    </span>
  ) : (
    <span className="inline-flex items-center rounded-full border border-dashed border-foreground/40 px-2.5 py-[3px] text-xs leading-snug text-muted-foreground">
      Estimare{detail ? ` · ${detail}` : ""}
    </span>
  );
}

const TAGS = {
  closure: "bg-closure-soft text-closure-ink",
  green: "bg-accent text-accent-foreground",
  neutral: "bg-muted text-muted-foreground",
  ink: "bg-foreground text-background",
} as const;

/** Status in words; colour only repeats what the word says. */
export function Tag({ tone = "neutral", children }: { tone?: keyof typeof TAGS; children: ReactNode }) {
  return <span className={cn("inline-flex h-6 items-center whitespace-nowrap rounded-md px-2 text-xs font-medium", TAGS[tone])}>{children}</span>;
}

export function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2.5" aria-busy="true" aria-label="Se încarcă">
      {Array.from({ length: rows }, (_, i) => <div key={i} className="h-11 animate-pulse rounded-lg bg-muted" />)}
    </div>
  );
}

export function Problem({ children }: { children: ReactNode }) {
  return <p role="alert" className="rounded-lg bg-closure-soft px-4 py-3 text-sm leading-snug text-closure-ink">{children}</p>;
}

export function Method({ children }: { children: ReactNode }) {
  return <p className="mt-3 text-xs leading-relaxed text-muted-foreground">{children}</p>;
}

/** A dot that says the number beside it is read from the live data right now. */
export function LiveDot() {
  return (
    <span className="relative flex size-2 shrink-0" aria-hidden>
      <span className="absolute inline-flex size-full rounded-full bg-primary/50 motion-safe:animate-ping" />
      <span className="relative inline-flex size-2 rounded-full bg-primary" />
    </span>
  );
}

/** A number that counts to its new value when it changes (anime.js on a plain object). Used by the landing map. */
export function Count({ value }: { value: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const prev = useRef(value);
  useEffect(() => {
    const from = prev.current;
    prev.current = value;
    if (from === value || !ref.current) return;
    const o = { v: from };
    const a = animeAnimate(o, { v: value, duration: 800, ease: "outExpo", onUpdate: () => { if (ref.current) ref.current.textContent = fmt.format(Math.round(o.v)); } });
    return () => { a.pause(); };
  }, [value]);
  return <span ref={ref}>{fmt.format(value)}</span>;
}
