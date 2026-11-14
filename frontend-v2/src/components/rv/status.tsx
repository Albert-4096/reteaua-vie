import { cn } from "@/lib/utils";
import { LEVEL_WORD, type Level } from "@/lib/acum";
import type { Route } from "@/lib/api";

/** Map colours mirror the --st-* tokens (MapLibre does not read oklch). */
export const STATUS_HEX: Record<Level, string> = { 3: "#cf3a2c", 2: "#c47a12", 1: "#2f6fc4", 0: "#8a93a3" };

const tone: Record<Level, string> = {
  3: "text-st-none",
  2: "text-st-reduced-ink",
  1: "text-st-info",
  0: "text-muted-foreground",
};

/** Shape + word, never colour alone: square = fără serviciu, triangle = redus, circle = informare. */
export function StatusMark({ level, className }: { level: Level; className?: string }) {
  const c = STATUS_HEX[level];
  return (
    <svg viewBox="0 0 12 12" aria-hidden className={cn("size-3 shrink-0", className)}>
      {level === 3 && <rect x="1.5" y="1.5" width="9" height="9" rx="1.5" fill={c} />}
      {level === 2 && <path d="M6 1.2 11 10.5H1Z" fill={c} />}
      {level === 1 && <circle cx="6" cy="6" r="4.5" fill={c} />}
      {level === 0 && <circle cx="6" cy="6" r="4" fill="none" stroke={c} strokeWidth="1.5" />}
    </svg>
  );
}

export function Status({ level, className, label }: { level: Level; className?: string; label?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", tone[level], className)}>
      <StatusMark level={level} />
      {label ?? LEVEL_WORD[level]}
    </span>
  );
}

export function LineBadge({ route, size = "md" }: { route: Route; size?: "sm" | "md" | "lg" }) {
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center rounded-[5px] font-semibold tnum leading-none",
        size === "sm" && "h-5 min-w-5 px-1 text-[11px]",
        size === "md" && "h-6 min-w-6 px-1.5 text-xs",
        size === "lg" && "h-9 min-w-9 px-2 text-base",
      )}
      style={{ background: `#${route.color}`, color: `#${route.textColor}` }}
      title={route.longName}
    >
      {route.shortName}
    </span>
  );
}

export function Announced({ yes, note }: { yes: boolean; note?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium",
        yes ? "bg-secondary text-muted-foreground" : "bg-st-none-soft text-st-none",
      )}
      title={note}
    >
      <span className={cn("size-1.5 rounded-full", yes ? "bg-muted-foreground/60" : "bg-st-none")} />
      {yes ? "Anunțat" : "Neanunțat"}
    </span>
  );
}
