import { motion } from "motion/react";
import { api, fmt, hhmm, useApi } from "@/lib/api";
import { cn } from "@/lib/utils";

const TRAM_WORKS = "cl_20261108_16dec";

const dayTime = (iso: string) =>
  new Date(iso).toLocaleString("ro-RO", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Bucharest" });
const sameDay = (a: string, b: string) =>
  new Date(a).toLocaleDateString("ro-RO", { timeZone: "Europe/Bucharest" }) === new Date(b).toLocaleDateString("ro-RO", { timeZone: "Europe/Bucharest" });
const span = (w: { start: string; end: string }) => `${dayTime(w.start)} – ${sameDay(w.start, w.end) ? hhmm(w.end) : dayTime(w.end)}`;
const times = new Intl.NumberFormat("ro-RO", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/** The Bd. 16 Decembrie tram works as proof under the hero: the notice's window against the proposed one. Numbers only from the API. */
export function Proof() {
  const im = useApi(() => api.impact(TRAM_WORKS));
  const w = useApi(() => api.windows(TRAM_WORKS));
  if (im.error || w.error) return null;

  const base = im.data?.totals.departuresLost;
  const best = w.data?.candidates[0];
  const ready = im.data != null && base != null && best != null;
  const rows = [
    { label: "Fereastra din anunț", when: im.data ? span(im.data.window) : "", n: base, share: 1, bar: "bg-closure", ink: "text-closure-ink" },
    { label: "Fereastra propusă", when: best ? span(best.window) : "", n: best?.departuresLost, share: base && best ? best.departuresLost / base : 0, bar: "bg-green", ink: "text-primary" },
  ];

  return (
    <div className="mx-auto mt-10 max-w-3xl rounded-xl border bg-card px-6 py-5 text-left shadow-card md:px-8 md:py-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h2 className="text-base font-semibold tracking-tight">Lucrarea la tramvai de pe Bd. 16 Decembrie 1989</h2>
        <span className="text-sm text-muted-foreground">din anunțul STPT pentru 8 nov</span>
      </div>
      <div className="mt-5 space-y-4">
        {rows.map((r, i) => (
          <div key={r.label} className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-2 md:grid-cols-[19rem_1fr_5rem]">
            <div className="col-span-2 md:col-span-1">
              <p className="text-sm font-medium">{r.label}</p>
              <p className="tabular min-h-5 text-sm text-muted-foreground">{r.when}</p>
            </div>
            {ready ? (
              <div className="h-3 overflow-hidden rounded-full bg-muted">
                <motion.div className={cn("h-full rounded-full", r.bar)} initial={{ width: 0 }} animate={{ width: `${r.share * 100}%` }}
                  transition={{ duration: 1.1, delay: 0.5 + i * 0.25, ease: [0.16, 1, 0.3, 1] }} />
              </div>
            ) : (
              <div className="h-3 animate-pulse rounded-full bg-muted" />
            )}
            <span className={cn("tabular w-20 text-right text-2xl font-semibold tracking-tight", r.ink)}>{ready && r.n != null ? fmt.format(r.n) : "–"}</span>
          </div>
        ))}
      </div>
      <div className="mt-5 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-t pt-4 text-sm">
        <span className="text-muted-foreground">Plecări pierdute. Estimare pe orarul planificat SMTT.</span>
        {ready && best!.departuresLost > 0 && (
          <span className="font-medium">Aceeași lucrare, aceleași 8 ore: de {times.format(base! / best!.departuresLost)} ori mai puține</span>
        )}
      </div>
    </div>
  );
}
