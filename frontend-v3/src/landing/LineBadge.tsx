import { cn } from "@/lib/utils";

/** Line number chip. Trams solid ink, trolleybuses tinted, buses outlined: mode reads before the number. */
export function LineBadge({ routeId, label, size = "md" }: { routeId: string; label?: string; size?: "md" | "lg" }) {
  const name = label ?? routeId.replace(/^R_[A-Z]+_/, "");
  const mode = routeId.startsWith("R_TV_") ? "tram" : routeId.startsWith("R_TB_") ? "troleibuz" : "autobuz";
  return (
    <span
      title={`${mode} ${name}`}
      className={cn(
        "tabular inline-flex items-center justify-center rounded-md font-semibold tracking-tight",
        size === "lg" ? "h-9 min-w-9 px-2 text-sm" : "h-6 min-w-6 px-1.5 text-xs",
        mode === "tram" && "bg-foreground text-background",
        mode === "troleibuz" && "bg-secondary text-secondary-foreground",
        mode === "autobuz" && "border border-foreground/25 bg-card text-foreground",
      )}
    >
      {name}
    </span>
  );
}
