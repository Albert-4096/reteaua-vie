import type { ReactNode } from "react";
import { Clock } from "lucide-react";
import { Logo } from "@/landing/Logo";
import { useApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { app } from "./data";
import { STEPS, go, useRoute, type StepId } from "./router";
import { Overview, Plan, Decide, Publish, Monitor, Report } from "./screens";

const SCREENS: Record<StepId, (p: { closureId: string }) => ReactNode> = {
  ansamblu: Overview, planifici: Plan, decizi: Decide, publici: Publish, urmaresti: Monitor, raportezi: Report,
};
const PICKER: StepId[] = ["planifici", "decizi", "publici", "urmaresti"];

export function App() {
  const { step, closureId } = useRoute();
  const closures = useApi(app.closures);
  const Screen = SCREENS[step];
  const current = STEPS.find((s) => s.id === step)!;

  return (
    <div className="flex h-dvh bg-background text-foreground">
      <aside className="flex w-64 shrink-0 flex-col border-r bg-card">
        <a href="/" className="flex h-16 items-center gap-2.5 px-5 font-semibold tracking-tight">
          <Logo className="size-8" /> Rețeaua Vie
        </a>
        <nav className="flex-1 px-3 py-3" aria-label="Pașii lucrării">
          <ol className="space-y-1">
            {STEPS.map((s, i) => {
              const on = s.id === step;
              return (
                <li key={s.id}>
                  <button type="button" onClick={() => go(s.id)} aria-current={on ? "page" : undefined}
                    className={cn("flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors",
                      on ? "bg-accent text-accent-foreground" : "text-foreground/80 hover:bg-muted")}>
                    <span className={cn("tabular grid size-6 shrink-0 place-items-center rounded-full text-xs font-semibold",
                      on ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground")}>{i + 1}</span>
                    <span className="leading-tight">
                      <span className="block text-[0.95rem] font-medium">{s.label}</span>
                      <span className={cn("block text-xs", on ? "text-accent-foreground/80" : "text-muted-foreground")}>{s.hint}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>
        <div className="border-t px-5 py-4 text-xs leading-relaxed text-muted-foreground">
          Date: orarul SMTT (GTFS), endpointurile Primăriei, anunțurile STPT. Populația: model GHSL 2020.
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center gap-5 border-b bg-card px-6">
          <h1 className="text-lg font-semibold tracking-tight">{current.label}</h1>
          {PICKER.includes(step) && (
            <label className="flex min-w-0 items-center gap-2 text-sm">
              <span className="text-muted-foreground">Lucrarea</span>
              <select value={closureId} onChange={(e) => go(step, e.target.value)}
                className="h-9 min-w-0 max-w-[34rem] truncate rounded-md border bg-background px-2.5 text-sm font-medium">
                {(closures.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.title.ro}</option>)}
              </select>
            </label>
          )}
          <span className="ml-auto inline-flex items-center gap-1.5 rounded-full border bg-background px-3 py-1.5 text-sm text-muted-foreground">
            <Clock className="size-3.5" /> Ceas simulat: duminică 8 nov 2026, 12:00
          </span>
        </header>
        <main className="min-h-0 flex-1">
          <Screen key={`${step}-${closureId}`} closureId={closureId} />
        </main>
      </div>
    </div>
  );
}

/** Side panel + map, the layout of every step that has a place on the map. */
export function Split({ panel, map }: { panel: ReactNode; map: ReactNode }) {
  return (
    <div className="grid h-full grid-cols-[30rem_1fr]">
      <div id="content" className="min-h-0 overflow-y-auto border-r bg-card">{panel}</div>
      <div className="relative min-h-0">{map}</div>
    </div>
  );
}
