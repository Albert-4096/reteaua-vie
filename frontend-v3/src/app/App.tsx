import { useEffect, useState, type ReactNode } from "react";
import { Check, ChevronsUpDown, Clock } from "lucide-react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { app, day, dt } from "./data";
import { MapView } from "./MapView";
import { go, useRoute, type StepId } from "./router";
import { StepBar } from "./StepBar";
import { Overview, Plan, Decide, Publish, Monitor, Report } from "./screens";
import { MapCtx, type Layers } from "./ui";

const SCREENS: Record<StepId, (p: { closureId: string }) => ReactNode> = {
  ansamblu: Overview, planifici: Plan, decizi: Decide, publici: Publish, urmaresti: Monitor, raportezi: Report,
};
const PICKER: StepId[] = ["planifici", "decizi", "publici", "urmaresti"];
const PANEL = 432; // 27rem
const EASE = [0.16, 1, 0.3, 1] as const;

function useViewportWidth() {
  const [w, setW] = useState(() => window.innerWidth);
  useEffect(() => {
    const on = () => setW(window.innerWidth);
    addEventListener("resize", on);
    return () => removeEventListener("resize", on);
  }, []);
  return w;
}

/**
 * One map under everything; one floating panel on the left that holds the current step;
 * the six steps in a floating bar. Raportezi has no map, so the panel widens into a sheet.
 */
export function App() {
  const { step, closureId } = useRoute();
  const [layers, setLayers] = useState<Layers>({ fitTo: "city" });
  const vw = useViewportWidth();
  const Screen = SCREENS[step];
  const wide = step === "raportezi";

  return (
    <MotionConfig reducedMotion="user">
      <MapCtx.Provider value={setLayers}>
        <div className="relative h-dvh overflow-hidden bg-background text-foreground">
          <div className="absolute inset-0">
            <MapView {...layers} padLeft={PANEL + 16} onClosure={(id) => go("planifici", id)} />
          </div>
          <ClockChip />

          <motion.aside initial={false} animate={{ width: wide ? vw - 32 : PANEL }} transition={{ duration: 0.3, ease: EASE }}
            className="absolute bottom-4 left-4 top-4 z-30 flex flex-col overflow-hidden rounded-2xl border bg-card shadow-float">
            {PICKER.includes(step) && <WorkPicker step={step} closureId={closureId} />}
            <AnimatePresence mode="wait" initial={false}>
              <motion.div key={`${step}-${closureId}`} className="min-h-0 flex-1"
                initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -10 }} transition={{ duration: 0.18, ease: "easeOut" }}>
                <Screen closureId={closureId} />
              </motion.div>
            </AnimatePresence>
          </motion.aside>

          <StepBar step={step} wide={wide} />
        </div>
      </MapCtx.Provider>
    </MotionConfig>
  );
}

/** Which work the steps are about. A popover list instead of a long select. */
function WorkPicker({ step, closureId }: { step: StepId; closureId: string }) {
  const closures = useApi(app.closures);
  const [open, setOpen] = useState(false);
  const cur = closures.data?.find((c) => c.id === closureId);
  return (
    <div className="border-b px-3 py-3">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring">
          <span className="size-2.5 shrink-0 rounded-full bg-closure" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="line-clamp-2 text-sm font-medium leading-snug">{cur?.title.ro ?? "Se încarcă lucrarea…"}</span>
            {cur && <span className="tabular mt-0.5 block text-xs text-muted-foreground">{dt(cur.window.start)} – {dt(cur.window.end)}</span>}
          </span>
          <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" />
          <span className="sr-only">Schimbă lucrarea</span>
        </PopoverTrigger>
        <PopoverContent align="start" sideOffset={6} className="w-[25rem] p-1.5">
          <ul>
            {(closures.data ?? []).map((c) => (
              <li key={c.id}>
                <button type="button" onClick={() => { setOpen(false); go(step, c.id); }}
                  className="flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-muted">
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium leading-snug">{c.title.ro}</span>
                    <span className="tabular mt-0.5 block text-xs text-muted-foreground">
                      {day(c.window.start)} – {day(c.window.end)} · {c.status === "published" ? "publicată" : "nepublicată"}
                    </span>
                  </span>
                  <Check className={cn("mt-0.5 size-4 shrink-0 text-primary", c.id !== closureId && "invisible")} />
                </button>
              </li>
            ))}
          </ul>
        </PopoverContent>
      </Popover>
    </div>
  );
}

/** The simulated clock, small; the data sources live behind it. */
function ClockChip() {
  return (
    <Popover>
      <PopoverTrigger className="absolute right-4 top-4 z-20 inline-flex h-10 items-center gap-2 rounded-full border bg-card/95 px-3.5 text-sm shadow-card outline-none backdrop-blur transition-colors hover:bg-card focus-visible:ring-2 focus-visible:ring-ring">
        <Clock className="size-4 text-muted-foreground" />
        <span className="tabular font-medium">Dum. 8 nov, 12:00</span>
        <span className="text-muted-foreground">simulat</span>
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={8} className="w-80 text-sm leading-relaxed">
        <p className="font-medium">Ceas simulat</p>
        <p className="mt-1 text-muted-foreground">Platforma arată pașii ca în duminica de 8 noiembrie, ziua lucrării de pe Bd. 16 Decembrie 1989. Vehiculele de pe hartă vin din datele live ale Primăriei, acum.</p>
        <p className="mt-3 font-medium">Surse</p>
        <p className="mt-1 text-muted-foreground">Orarul SMTT (GTFS), endpointurile Primăriei, anunțurile STPT, pozițiile vehiculelor înregistrate de noi la 15 s. Populația: model GHSL 2020.</p>
      </PopoverContent>
    </Popover>
  );
}

