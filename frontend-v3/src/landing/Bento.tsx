import type { ReactNode } from "react";
import { motion } from "motion/react";
import { QrCode, Volume2, BellRing, Check } from "lucide-react";
import { api, fmt, hhmm, useApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { LineBadge } from "./LineBadge";

const TRAM_WORKS = "cl_20261108_16dec";

/** `wide`: a full-row card, text beside the visual from md up. */
function Card({ title, body, children, className, wide }: { title: string; body: string; children: ReactNode; className?: string; wide?: boolean }) {
  return (
    <article className={cn("flex flex-col overflow-hidden rounded-xl border bg-card shadow-card", wide && "md:flex-row-reverse md:items-center", className)}>
      <div className={cn("relative flex min-h-64 flex-1 items-center justify-center px-8 pt-10", wide && "md:pb-10")}>{children}</div>
      <div className={cn("px-8 pb-8 pt-6", wide && "md:flex-1 md:py-10 md:pl-12")}>
        <h3 className="display text-[1.65rem] leading-tight">{title}</h3>
        <p className="mt-2 max-w-[46ch] text-[0.97rem] leading-relaxed text-muted-foreground">{body}</p>
      </div>
    </article>
  );
}

function ImpactVisual() {
  const c = useApi(() => api.closure(TRAM_WORKS));
  const im = useApi(() => api.impact(TRAM_WORKS));
  const t = im.data?.totals;
  return (
    <div className="w-full max-w-sm -rotate-2 rounded-lg border bg-card p-5 shadow-float">
      <div className="flex items-center gap-1.5">
        {(c.data?.routeIds ?? []).map((r) => <LineBadge key={r} routeId={r} />)}
      </div>
      <p className="mt-3 text-sm font-medium leading-snug">{c.data?.title.ro ?? "Se încarcă lucrarea…"}</p>
      <dl className="mt-4 grid grid-cols-2 gap-3">
        <div className="rounded-md bg-closure-soft px-3 py-2.5">
          <dt className="text-xs text-closure-ink">Plecări pierdute</dt>
          <dd className="tabular text-2xl font-semibold tracking-tight">{t ? fmt.format(t.departuresLost) : "–"}</dd>
        </div>
        <div className="rounded-md bg-muted px-3 py-2.5">
          <dt className="text-xs text-muted-foreground">Stații suspendate</dt>
          <dd className="tabular text-2xl font-semibold tracking-tight">{t ? fmt.format(t.stopsSuspended) : "–"}</dd>
        </div>
      </dl>
      <p className="mt-3 text-xs text-muted-foreground">Estimare pe orarul planificat SMTT</p>
    </div>
  );
}

function VehiclesVisual() {
  const m = useApi(api.missing, 60000);
  const rows = (m.data?.routes ?? []).filter((r) => r.state === "fara_vehicul").slice(0, 3);
  return (
    <div className="w-full max-w-md space-y-2.5">
      {!m.data && !m.error && [0, 1].map((i) => <div key={i} className="h-16 animate-pulse rounded-lg bg-muted" />)}
      {m.error && <div className="rounded-lg border bg-card p-4 text-sm shadow-card">Datele live nu răspund acum. Reîncercăm în 60 de secunde.</div>}
      {m.data && rows.length === 0 && (
        <div className="rounded-lg border bg-card p-4 text-sm shadow-card">Toate liniile din orar au vehicule în datele live acum.</div>
      )}
      {rows.map((r, i) => (
        <motion.div key={r.routeId} initial={{ opacity: 0, y: 8 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
          transition={{ delay: i * 0.12, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
          className="flex items-center gap-3 rounded-lg border bg-card p-3.5 shadow-card">
          <LineBadge routeId={r.routeId} label={r.shortName} size="lg" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{r.longName}</p>
            <p className="tabular text-xs text-muted-foreground">
              Fără vehicul în datele live · {r.tripsObserved} din {r.tripsInService} curse văzute
            </p>
          </div>
          <span className="inline-flex items-center gap-1 rounded-md bg-accent px-2.5 py-1.5 text-xs font-medium text-accent-foreground">
            <Check className="size-3.5" /> Confirmă
          </span>
        </motion.div>
      ))}
      {m.data && (
        <p className="pt-1 text-xs text-muted-foreground">
          Din datele live ale Primăriei, înregistrate de noi · {hhmm(m.data.window.start)}–{hhmm(m.data.window.end)}
        </p>
      )}
    </div>
  );
}

function CitizenVisual() {
  return (
    <div className="relative h-56 w-full max-w-sm">
      <figure className="absolute left-0 top-0 w-44 rotate-[-6deg]">
        <div className="rounded-md border bg-card p-3.5 shadow-float">
          <div className="h-1.5 w-10 rounded-full bg-closure" />
          <p className="mt-2.5 text-sm font-semibold leading-tight">Linia E3 deviată</p>
          <p className="mt-1 text-xs leading-snug text-muted-foreground">Str. Ardealului închisă. 11 stații nu sunt deservite.</p>
          <div className="mt-3 flex items-end justify-between">
            <QrCode className="size-12 text-foreground" strokeWidth={1.4} />
            <Volume2 className="size-4 text-muted-foreground" />
          </div>
        </div>
        <figcaption className="mt-2 text-xs text-muted-foreground">Afișul A4 din stație</figcaption>
      </figure>
      <div className="absolute -right-2 top-24 w-60 rotate-[3deg] rounded-lg border bg-card p-3.5 shadow-float">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <BellRing className="size-3.5 text-green" /> Alertă în aplicația de hărți
        </div>
        <p className="mt-1.5 text-sm font-medium leading-snug">Str. Ardealului închisă, linia E3 deviată</p>
        <p className="mt-1 text-xs text-muted-foreground">Previzualizare GTFS-RT, așa cum o pot citi CityApp și Google</p>
      </div>
    </div>
  );
}

export function Bento() {
  return (
    <div className="grid grid-cols-1 gap-5 md:grid-cols-12">
      <Card className="md:col-span-5" title="Primăria vede impactul înainte să aprobe."
        body="Liniile, stațiile, plecările și locuitorii afectați, calculate pe orarul real al SMTT pentru strada desenată pe hartă.">
        <ImpactVisual />
      </Card>
      <Card className="md:col-span-7" title="STPT vede ce au făcut vehiculele."
        body="Stațiile suspendate, ocolirile și liniile din orar fără niciun vehicul în datele live. Un om confirmă înainte ca semnalul să ajungă în CityApp.">
        <VehiclesVisual />
      </Card>
      <Card wide className="md:col-span-12" title="Călătorii află din ce folosesc deja."
        body="CityApp, Google Maps și afișul din stație, cu cod QR și versiune audio. Fără cont, fără o aplicație nouă.">
        <CitizenVisual />
      </Card>
    </div>
  );
}
