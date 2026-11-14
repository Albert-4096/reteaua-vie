import { cn } from "@/lib/utils";
import type { Issue } from "@/lib/acum";

/** The product's mechanism as one component: the timetable's figure, struck, beside the street's. */
export function PlannedVsActual({ issue, size = "md" }: { issue: Issue; size?: "md" | "lg" }) {
  const big = size === "lg";
  return (
    <div className="flex items-end gap-5">
      <div>
        <div className={cn("tnum font-semibold text-muted-foreground line-through decoration-2 decoration-muted-foreground/60", big ? "text-4xl" : "text-2xl")}>
          {issue.planned.value}
        </div>
        <div className="mt-1 text-xs text-muted-foreground">{issue.planned.label}</div>
      </div>
      <svg viewBox="0 0 24 12" className={cn("mb-6 shrink-0 text-muted-foreground/50", big ? "w-7" : "w-5")} aria-hidden>
        <path d="M0 6h21m-5-5 5 5-5 5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
      <div>
        <div className={cn("tnum font-semibold", issue.level === 3 ? "text-st-none" : "text-st-reduced-ink", big ? "text-4xl" : "text-2xl")}>
          {issue.actual.value}
        </div>
        <div className="mt-1 text-xs text-muted-foreground">{issue.actual.label}</div>
      </div>
    </div>
  );
}
