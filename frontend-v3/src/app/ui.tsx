import { createContext, useContext, useEffect, useRef, type ReactNode } from "react";
import { animate as animeAnimate } from "animejs";
import { CircleCheck } from "lucide-react";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { fmt } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { MapProps } from "./MapView";

/* ---------- the shared map: every step tells it what to show ---------- */
export type Layers = Omit<MapProps, "onClosure" | "padLeft">;
export const MapCtx = createContext<(l: Layers) => void>(() => {});
export function useMapLayers(l: Layers) {
  const set = useContext(MapCtx);
  useEffect(() => set(l), [set, l]);
}

/**
 * The one layout of every step: the question the step answers, one answer in large type,
 * the rest folded, one next action at the bottom.
 */
export function Step({ title, answer, children, footer, inner }: { title: string; answer?: ReactNode; children?: ReactNode; footer?: ReactNode; inner?: string }) {
  return (
    <div className="flex h-full flex-col">
      <div id="content" className="min-h-0 flex-1 overflow-y-auto px-6 pb-8 pt-6">
        <div className={inner}>
          <h2 className="text-[1.4rem] font-semibold leading-tight tracking-tight">{title}</h2>
          {answer}
          {children}
        </div>
      </div>
      {footer && <div className="border-t bg-card px-5 py-4">{footer}</div>}
    </div>
  );
}

/** The step's answer: one number, what it counts, and whether we measured or estimated it. */
export function Answer({ value, label, kind, tone, children }: { value: ReactNode; label: ReactNode; kind?: ReactNode; tone?: "closure" | "green"; children?: ReactNode }) {
  return (
    <div className="mt-5">
      <div className={cn("tabular text-[3.4rem] font-semibold leading-none tracking-tight transition-colors duration-300",
        tone === "closure" && "text-closure-ink", tone === "green" && "text-accent-foreground")}>{value}</div>
      <div className="mt-2.5 text-[0.95rem] leading-snug text-foreground/80">{label}</div>
      {kind && <div className="mt-3">{kind}</div>}
      {children}
    </div>
  );
}

/** A smaller supporting number, next to the answer. */
export function Stat({ value, label, kind }: { value: ReactNode; label: string; kind?: "measured" | "estimate" }) {
  return (
    <div>
      <div className="tabular text-xl font-semibold leading-none tracking-tight">{value}</div>
      <div className="mt-1.5 text-sm leading-snug text-muted-foreground">{label}{kind === "estimate" && <span className="ml-1 whitespace-nowrap text-xs">(estimare)</span>}</div>
    </div>
  );
}

/** Details that wait until asked for: shadcn Accordion, closed by default. */
export function Folds({ children, open, className }: { children: ReactNode; open?: string[]; className?: string }) {
  return <Accordion type="multiple" defaultValue={open} className={cn("mt-7 border-t", className)}>{children}</Accordion>;
}
export function Fold({ id, title, aside, children }: { id: string; title: ReactNode; aside?: ReactNode; children: ReactNode }) {
  return (
    <AccordionItem value={id}>
      <AccordionTrigger className="items-center py-4 text-[0.95rem] hover:no-underline">
        <span className="flex flex-1 items-baseline justify-between gap-3">
          <span>{title}</span>
          {aside != null && <span className="tabular text-sm font-normal text-muted-foreground">{aside}</span>}
        </span>
      </AccordionTrigger>
      <AccordionContent className="pb-5">{children}</AccordionContent>
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
    <span title="Estimare pe orarul planificat SMTT" className="inline-flex items-center whitespace-nowrap rounded-full border border-dashed border-foreground/40 px-2.5 py-[3px] text-xs text-muted-foreground">
      Estimare{detail ? ` · ${detail}` : ""}
    </span>
  );
}

/** A number that counts to its new value when it changes (anime.js on a plain object). */
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
    <div className="space-y-2.5" aria-busy="true">
      {Array.from({ length: rows }, (_, i) => <div key={i} className="h-12 animate-pulse rounded-lg bg-muted" />)}
    </div>
  );
}

export function Problem({ children }: { children: ReactNode }) {
  return <p className="rounded-lg bg-closure-soft px-4 py-3 text-sm text-closure-ink">{children}</p>;
}

export function Method({ children }: { children: ReactNode }) {
  return <p className="mt-3 text-xs leading-relaxed text-muted-foreground">{children}</p>;
}
