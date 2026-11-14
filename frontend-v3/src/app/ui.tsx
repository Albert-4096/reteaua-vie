import { useEffect, useRef, type ReactNode } from "react";
import { animate } from "motion";
import { CircleCheck } from "lucide-react";
import { fmt } from "@/lib/api";
import { cn } from "@/lib/utils";

/** A titled block in the side panel. Sections are separated by space and a rule, never boxed. */
export function Section({ title, aside, children, className }: { title: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("border-t px-6 py-6 first:border-t-0", className)}>
      <div className="mb-4 flex items-baseline justify-between gap-4">
        <h2 className="text-[1.05rem] font-semibold tracking-tight">{title}</h2>
        {aside && <div className="text-sm text-muted-foreground">{aside}</div>}
      </div>
      {children}
    </section>
  );
}

/** A number with its label underneath and, when it is not a count we observed, the method in words. */
export function Figure({ value, label, note, tone, kind }: { value: ReactNode; label: string; note?: string; tone?: "closure" | "green"; kind?: "measured" | "estimate" }) {
  return (
    <div>
      <div className={cn("tabular text-[1.9rem] font-semibold leading-none tracking-tight", tone === "closure" && "text-closure-ink", tone === "green" && "text-accent-foreground")}>{value}</div>
      <div className="mt-1.5 text-sm text-foreground/80">{label}</div>
      {note && <div className="text-xs text-muted-foreground">{note}</div>}
      {kind && <div className="mt-2"><Kind k={kind} /></div>}
    </div>
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

/** A number that counts to its new value when it changes. */
export function Count({ value }: { value: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const prev = useRef(value);
  useEffect(() => {
    const from = prev.current;
    prev.current = value;
    if (from === value) return;
    const c = animate(from, value, { duration: 0.9, ease: [0.16, 1, 0.3, 1], onUpdate: (v) => { if (ref.current) ref.current.textContent = fmt.format(Math.round(v)); } });
    return () => c.stop();
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
