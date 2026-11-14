import { cn } from "@/lib/utils";
import { inkOn, useNetwork } from "@/lib/network";

/** Line number chip in the city's own line colour (GTFS route_color), as on STPT stops and vehicles. */
export function LineBadge({ routeId, label, size = "md" }: { routeId: string; label?: string; size?: "md" | "lg" }) {
  const net = useNetwork();
  const r = net?.byId.get(routeId);
  const name = label ?? r?.shortName ?? routeId.replace(/^R_[A-Z]+_/, "");
  return (
    <span
      title={r ? `${r.shortName} · ${r.longName}` : name}
      className={cn(
        "tabular inline-flex items-center justify-center rounded-md font-semibold tracking-tight",
        size === "lg" ? "h-9 min-w-9 px-2 text-sm" : "h-6 min-w-6 px-1.5 text-xs",
        !r && "bg-secondary text-secondary-foreground",
      )}
      style={r ? { background: `#${r.color}`, color: inkOn(r.color) } : undefined}
    >
      {name}
    </span>
  );
}
