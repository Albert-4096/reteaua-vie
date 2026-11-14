import { useEffect } from "react";
import { motion } from "motion/react";
import { Kbd } from "@/components/ui/kbd";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { Logo } from "@/landing/Logo";
import { STEPS, go, type StepId } from "./router";

const PILL = { type: "spring", bounce: 0.18, duration: 0.5 } as const;

/**
 * The six steps as one floating bar over the map (right of the 30rem panel, so it never covers the panel's buttons);
 * centred on the page for steps without a map (`wide`), gliding between the two places.
 * The green pill slides to the current step; digits 1–6 jump to a step.
 */
export function StepBar({ step, wide = false }: { step: StepId; wide?: boolean }) {
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.repeat) return;
      const t = e.target as HTMLElement | null;
      if (t?.closest("input, select, textarea, [contenteditable]")) return;
      const n = Number(e.key);
      if (n >= 1 && n <= STEPS.length) go(STEPS[n - 1].id);
    };
    addEventListener("keydown", on);
    return () => removeEventListener("keydown", on);
  }, []);

  return (
    <TooltipProvider delayDuration={250}>
      <nav aria-label="Pașii lucrării" className={cn("pointer-events-none fixed bottom-5 right-0 z-40 flex justify-center px-4", wide ? "left-0" : "left-[28rem]")}>
        <motion.ol
          layout="position"
          initial={{ y: 28, opacity: 0, filter: "blur(6px)" }}
          animate={{ y: 0, opacity: 1, filter: "blur(0px)" }}
          transition={{ type: "spring", bounce: 0.2, duration: 0.7, delay: 0.15, layout: { type: "spring", bounce: 0.15, duration: 0.55 } }}
          className="pointer-events-auto flex items-center gap-0.5 rounded-full border bg-card/92 p-1.5 shadow-[0_18px_40px_-16px_oklch(0.25_0.02_165/0.45),0_2px_6px_oklch(0.25_0.02_165/0.08)] backdrop-blur-md"
        >
          <li className="flex items-center pl-1 pr-1.5">
            <a href="/" aria-label="Rețeaua Vie, pagina principală" className="grid size-9 place-items-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <Logo className="size-7" />
            </a>
            <span aria-hidden className="ml-2.5 h-6 w-px bg-border" />
          </li>
          {STEPS.map((s, i) => {
            const on = s.id === step;
            return (
              <li key={s.id}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      onClick={() => go(s.id)}
                      aria-current={on ? "step" : undefined}
                      className={cn(
                        "relative flex h-10 items-center gap-2 rounded-full pl-1.5 pr-3.5 text-sm font-medium outline-none transition-colors duration-200",
                        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card",
                        on ? "text-primary-foreground" : "text-foreground/75 hover:bg-muted hover:text-foreground",
                      )}
                    >
                      {on && <motion.span layoutId="step-pill" transition={PILL} className="absolute inset-0 rounded-full bg-primary shadow-[0_4px_12px_-4px_oklch(0.5_0.095_166/0.6)]" />}
                      <span className={cn("tabular relative grid size-7 place-items-center rounded-full text-xs font-semibold transition-colors duration-200",
                        on ? "bg-black/20 text-primary-foreground" : "bg-muted text-muted-foreground")}>{i + 1}</span>
                      <span className="relative hidden whitespace-nowrap sm:inline">{s.label}</span>
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="top" sideOffset={12} className="flex items-center gap-2">
                    {s.hint} <Kbd>{i + 1}</Kbd>
                  </TooltipContent>
                </Tooltip>
              </li>
            );
          })}
        </motion.ol>
      </nav>
    </TooltipProvider>
  );
}
