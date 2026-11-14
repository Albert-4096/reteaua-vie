import type { ReactNode } from "react";
import { Clock, Info } from "lucide-react";
import { MotionConfig, motion } from "motion/react";
import { Logo } from "@/landing/Logo";
import { useApi } from "@/lib/api";
import { app } from "./data";
import { STEPS, go, useRoute, type StepId } from "./router";
import { StepBar } from "./StepBar";
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
    <MotionConfig reducedMotion="user">
      <div className="flex h-dvh flex-col bg-background text-foreground">
        <header className="flex h-14 shrink-0 items-center gap-4 border-b bg-card px-5">
          <a href="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <Logo className="size-7" /> Rețeaua Vie
          </a>
          <span aria-hidden className="h-5 w-px bg-border" />
          <h1 className="flex items-baseline gap-2 whitespace-nowrap">
            <span className="text-[1.05rem] font-semibold tracking-tight">{current.label}</span>
            <span className="hidden text-sm text-muted-foreground lg:inline">{current.hint}</span>
          </h1>
          {PICKER.includes(step) && (
            <label className="ml-2 flex min-w-0 items-center gap-2 text-sm">
              <span className="text-muted-foreground">Lucrarea</span>
              <select value={closureId} onChange={(e) => go(step, e.target.value)}
                className="h-9 min-w-0 max-w-[30rem] truncate rounded-md border bg-background px-2.5 text-sm font-medium">
                {(closures.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.title.ro}</option>)}
              </select>
            </label>
          )}
          <div className="ml-auto flex shrink-0 items-center gap-2">
            <span title="Date: orarul SMTT (GTFS), endpointurile Primăriei, anunțurile STPT. Populația: model GHSL 2020."
              className="hidden cursor-help items-center gap-1.5 text-sm text-muted-foreground xl:inline-flex">
              <Info className="size-3.5" /> Surse
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border bg-background px-3 py-1.5 text-sm text-muted-foreground">
              <Clock className="size-3.5" /> Ceas simulat: duminică 8 nov 2026, 12:00
            </span>
          </div>
        </header>
        <motion.main key={`${step}-${closureId}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.22, ease: "easeOut" }}
          className="min-h-0 flex-1">
          <Screen closureId={closureId} />
        </motion.main>
        <StepBar step={step} wide={step === "raportezi"} />
      </div>
    </MotionConfig>
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
