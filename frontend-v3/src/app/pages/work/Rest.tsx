import { useState } from "react";
import { ArrowRight, Check, Download, ExternalLink, FileText, Megaphone, Network, QrCode, Radio, Route, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LineBadge } from "@/landing/LineBadge";
import { useApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { app, count, day, dt, fmt, hhmm, uniq, when, type ClosureSummary, type GeneratedNotice } from "../../data";
import { link } from "../../router";
import { Fold, Folds, Kind, Loading, Method, Problem, Section, Stat, Tag } from "../../ui";

const MEASURED = "cl_20261102_mocioni"; // the work our vehicle recording covers

/* ---------------- Perioadă: when the works hurt least ---------------- */
export function Period({ id, c }: { id: string; c: ClosureSummary }) {
  const w = useApi(() => app.windows(id), undefined, id);
  const conflicts = useApi(() => app.conflicts(id), undefined, id);
  const measured = useApi(() => app.windowsMeasured(id), undefined, id);
  if (w.error) return <Problem>Perioadele nu s-au putut calcula ({w.error}).</Problem>;
  if (!w.data) return <Loading rows={4} />;

  const base = w.data.baselineDeparturesLost;
  const rows = w.data.candidates;
  const best = rows[0];
  const max = Math.max(base, ...rows.map((r) => r.departuresLost), 1);
  const pairs = uniq((conflicts.data ?? []).map((x) => x.otherClosureId)).map((o) => conflicts.data!.find((x) => x.otherClosureId === o)!);

  const Bar = ({ label, sub, value, tone }: { label: string; sub?: string; value: number; tone: "closure" | "green" | "plain" }) => (
    <li className="py-2.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="min-w-0 text-sm"><span className="font-medium">{label}</span>{sub && <span className="text-muted-foreground"> · {sub}</span>}</span>
        <span className="tabular text-sm font-semibold">{fmt.format(value)}</span>
      </div>
      <div className="mt-1.5 h-2 rounded-full bg-muted" aria-hidden>
        <div className={cn("h-full rounded-full", tone === "closure" ? "bg-closure" : tone === "green" ? "bg-primary" : "bg-foreground/35")} style={{ width: `${Math.max(1.5, (value / max) * 100)}%` }} />
      </div>
    </li>
  );
  const span = (x: { start: string; end: string }) => `${dt(x.start)} – ${hhmm(x.end)}`;

  return (
    <>
      <p className="text-[1.05rem] font-medium leading-snug">
        {best && best.departuresLost < base
          ? `Aceeași lucrare, mutată ${span(best.window)}, pierde ${count(best.departuresLost, "plecare", "plecări")} în loc de ${fmt.format(base)}.`
          : "Perioada din anunț este deja cea cu cele mai puține plecări pierdute."}
      </p>
      <div className="mt-4"><Kind k="estimate" detail="orarul planificat SMTT" /></div>

      <Section title="Plecări pierdute, pe perioadă" aside={`${w.data.hours} ore de lucru`}>
        <ul className="divide-y">
          <Bar label="Din anunț" sub={when(c.window)} value={base} tone="closure" />
          {rows.slice(0, 4).map((r, i) => <Bar key={r.window.start} label={i === 0 ? "Cel mai mic impact" : `Varianta ${i + 1}`} sub={span(r.window)} value={r.departuresLost} tone={i === 0 ? "green" : "plain"} />)}
        </ul>
        <Method>Căutat în intervalul {day(w.data.searchFrom)} – {day(w.data.searchTo)} Platforma propune; perioada o hotărăște Primăria.</Method>
      </Section>

      {measured.data && (
        <Section title="După traficul măsurat" aside={measured.data.candidates.length ? <Kind k="measured" /> : "necunoscut"}>
          {measured.data.candidates.length > 0 ? (
            <ol className="tabular space-y-1.5 text-sm">
              {measured.data.candidates.slice(0, 3).map((x, i) => <li key={x.window.start}><span className="font-medium">{i + 1}.</span> {span(x.window)}</li>)}
            </ol>
          ) : (
            <p className="text-sm leading-relaxed text-muted-foreground">{measured.data.note?.ro ?? "Înregistrarea nu acoperă încă ocolirile acestei lucrări."} De aceea ordinea de mai sus rămâne o estimare pe orar.</p>
          )}
          <Method>{measured.data.label.ro[0].toUpperCase() + measured.data.label.ro.slice(1)}.</Method>
        </Section>
      )}

      {pairs.length > 0 && (
        <Section title="Se suprapune cu alte lucrări" aside={pairs.length}>
          <ul className="space-y-3">
            {pairs.map((x) => (
              <li key={x.otherClosureId} className="text-sm leading-snug">
                <a {...link({ page: "lucrare", id: x.otherClosureId, tab: "impact" })} className="font-medium underline-offset-4 hover:underline">{x.otherTitle.ro}</a>
                <span className="tabular block text-muted-foreground">{day(x.overlap.start)} – {day(x.overlap.end)} · {count(x.routeIds.length, "linie comună", "linii comune")}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Folds>
        {rows.length > 4 && (
          <Fold id="more" title="Alte perioade" aside={rows.length - 4}>
            <ul className="divide-y">{rows.slice(4).map((r, i) => <Bar key={r.window.start} label={`Varianta ${i + 5}`} sub={span(r.window)} value={r.departuresLost} tone="plain" />)}</ul>
          </Fold>
        )}
        <Fold id="method" title="Cum calculăm"><p className="leading-relaxed text-muted-foreground">{w.data.method.ro}</p></Fold>
      </Folds>
    </>
  );
}

/* ---------------- Anunț: what riders are told, and where it goes ---------------- */
export function Notice({ id, c, notice, published }: { id: string; c: ClosureSummary; notice: GeneratedNotice | null; published: boolean }) {
  const zones = useApi(() => app.notices(id), undefined, `${id}${published}`);
  const [all, setAll] = useState(false);
  const posters = uniq((notice?.stopsWithNoService ?? []).map((s) => s.stopId)).slice(0, 3);
  const name = (stopId: string) => notice?.stopsWithNoService.find((s) => s.stopId === stopId)?.name ?? stopId;

  const channels: { icon: LucideIcon; name: string; who: string; href?: string }[] = [
    { icon: Radio, name: "Alerte GTFS-RT", who: "CityApp, Google Maps și alte aplicații o pot citi", href: "/api/feed/alerts.json" },
    { icon: Megaphone, name: "Anunțuri pe cartiere", who: zones.data?.length ? `site, rețele, avizier · ${count(zones.data.length, "cartier", "cartiere")}` : "site, rețele, avizier", href: "/api/feed/notices.json" },
    { icon: Route, name: "DATEX II", who: "Punctul Național de Acces", href: "/api/feed/datex.xml" },
    { icon: Network, name: "NGSI-LD", who: "platforma de date a orașului", href: "/api/feed/alerts.ngsi.json" },
    { icon: FileText, name: "Metadate NAP", who: "Punctul Național de Acces", href: "/api/exports/nap-metadata.json" },
  ];

  return (
    <>
      <p className="text-[1.05rem] font-medium leading-snug">Un singur text, scris o dată, pentru toate canalele. Numește fiecare stație și cea mai apropiată stație deservită.</p>

      <Section title="Ce află călătorii" aside={notice ? (notice.status === "final" ? <Tag tone="green">Gata de publicat</Tag> : <Tag tone="closure">Ciornă</Tag>) : undefined}>
        {!notice ? <Loading rows={3} /> : (
          <div className="rounded-xl bg-muted/70 p-4">
            <p className={cn("whitespace-pre-line text-sm leading-relaxed text-foreground/85", !all && "line-clamp-[9]")}>{notice.text.ro}</p>
            <button type="button" onClick={() => setAll((x) => !x)} className="mt-2 rounded text-sm font-medium text-accent-foreground underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">
              {all ? "Arată mai puțin" : "Arată tot textul"}
            </button>
          </div>
        )}
        {notice?.status === "draft" && <Method>Mai sunt {count(notice.unsureCount, "stație de hotărât", "stații de hotărât")} în Impact; textul se schimbă după răspuns.</Method>}
      </Section>

      <Section title="Unde pleacă" aside={published ? "publicat" : "la publicare"}>
        <ul className="divide-y">
          {channels.map((ch) => (
            <li key={ch.name} className="flex items-center gap-3 py-2.5 text-sm">
              <ch.icon className="size-4 shrink-0 text-muted-foreground" strokeWidth={1.8} />
              <span className="min-w-0 flex-1"><span className="block font-medium">{ch.name}</span><span className="block text-muted-foreground">{ch.who}</span></span>
              {ch.href && <a href={ch.href} target="_blank" rel="noreferrer" className="inline-flex shrink-0 items-center gap-1 font-medium text-accent-foreground underline-offset-4 hover:underline">Fișier <ExternalLink className="size-3.5" /></a>}
            </li>
          ))}
        </ul>
      </Section>

      {posters.length > 0 && (
        <Section title="Afișe pentru stații">
          <ul className="divide-y">
            {posters.map((s) => (
              <li key={s} className="flex items-center gap-3 py-2.5 text-sm">
                <QrCode className="size-4 shrink-0 text-muted-foreground" strokeWidth={1.8} />
                <span className="min-w-0 flex-1">{name(s)}</span>
                <a href={app.posterUrl(id, s)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-accent-foreground underline-offset-4 hover:underline"><Download className="size-3.5" /> PDF</a>
              </li>
            ))}
          </ul>
          <Method>A4, cu cod QR spre pagina stației și versiune audio.</Method>
        </Section>
      )}

      {c.sourceText && (
        <Folds>
          <Fold id="source" title="Anunțul original STPT">
            <p className="whitespace-pre-line leading-relaxed text-muted-foreground">{c.sourceText}</p>
            {c.sourceUrl && <a href={c.sourceUrl} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1 font-medium text-accent-foreground underline-offset-4 hover:underline">stpt.ro <ExternalLink className="size-3.5" /></a>}
          </Fold>
        </Folds>
      )}
    </>
  );
}

/** Publishing reaches citizens, so it asks twice and says plainly what happened. */
export function PublishBar({ id, openQuestions, published, onPublished }: { id: string; openQuestions: number; published: boolean; onPublished: () => void }) {
  const [state, setState] = useState<"idle" | "confirm" | "busy" | "error">("idle");
  const [err, setErr] = useState("");
  const publish = async () => {
    setState("busy");
    try { await app.publish(id); setState("idle"); onPublished(); } catch (e) { setErr((e as Error).message); setState("error"); }
  };

  if (published) {
    return (
      <div className="flex items-center justify-between gap-3">
        <p className="flex items-center gap-2 text-base font-medium text-accent-foreground"><Check className="size-4" />Publicată. Fluxurile sunt la zi.</p>
        <a {...link({ page: "lucrare", id, tab: "teren" })} className="inline-flex items-center gap-1 text-sm font-medium underline-offset-4 hover:underline">Pe teren <ArrowRight className="size-3.5" /></a>
      </div>
    );
  }
  if (openQuestions > 0) {
    return (
      <div>
        <Button className="h-11 w-full rounded-xl text-base" disabled>Publică lucrarea</Button>
        <p className="mt-2 text-sm text-muted-foreground">
          Mai {openQuestions === 1 ? "e o întrebare" : `sunt ${openQuestions} întrebări`} fără răspuns în{" "}
          <a {...link({ page: "lucrare", id, tab: "impact" })} className="font-medium text-foreground underline underline-offset-4">Impact</a>.
        </p>
      </div>
    );
  }
  return (
    <div>
      {state === "confirm" ? (
        <div className="flex gap-2">
          <Button className="h-11 flex-1 rounded-xl" onClick={publish}>Da, publică acum</Button>
          <Button variant="outline" className="h-11 rounded-xl" onClick={() => setState("idle")}><X className="size-4" /> Renunț</Button>
        </div>
      ) : (
        <Button className="h-11 w-full rounded-xl text-base" disabled={state === "busy"} onClick={() => setState("confirm")}>{state === "busy" ? "Se publică…" : "Publică lucrarea"}</Button>
      )}
      {state === "confirm" && <p className="mt-2 text-sm text-muted-foreground">Alerta pleacă spre toate canalele de mai sus.</p>}
      {state === "error" && <div className="mt-2"><Problem>Publicarea nu a reușit: {err}. Nimic nu a plecat; puteți încerca din nou.</Problem></div>}
    </div>
  );
}

/** A long explanation from the analysis: four lines, the rest on request. */
function Long({ text }: { text: string }) {
  const [all, setAll] = useState(false);
  return (
    <div>
      <p className={cn("text-sm leading-relaxed text-foreground/85", !all && "line-clamp-4")}>{text}</p>
      <button type="button" onClick={() => setAll((x) => !x)} className="mt-1 rounded text-sm font-medium text-accent-foreground underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">{all ? "Arată mai puțin" : "Arată tot"}</button>
    </div>
  );
}

/* ---------------- Pe teren: what vehicles really did ---------------- */
const minutes = (sec: number) => `${sec < 0 ? "−" : "+"}${fmt.format(Math.abs(Math.round(sec / 6) / 10))} min`;

export function Field({ id, c }: { id: string; c: ClosureSummary }) {
  const live = useApi(() => app.live(id), undefined, id);
  const cost = useApi(() => app.detourCost(id), undefined, id);
  if (live.error) return <Problem>Verificarea pe teren nu s-a încărcat ({live.error}).</Problem>;
  if (!live.data) return <Loading rows={4} />;

  const s = live.data.summary;
  if (s.vehiclesSeen == null) {
    return (
      <>
        <p className="text-[1.05rem] font-medium leading-snug">Pentru această lucrare nu avem vehicule înregistrate.</p>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          Înregistrăm pozițiile vehiculelor din datele live ale Primăriei{live.data.recordedFrom ? `, din ${dt(live.data.recordedFrom)}` : ""}. Lucrarea ({when(c.window)}) este în afara înregistrării, deci nu știm ce au făcut vehiculele: necunoscut, nu zero.
        </p>
        {id !== MEASURED && (
          <a {...link({ page: "lucrare", id: MEASURED, tab: "teren" })} className="mt-5 flex items-center gap-3 rounded-xl border px-4 py-3 text-sm outline-none transition-colors hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring">
            <span className="min-w-0 flex-1"><span className="block font-medium">O lucrare măsurată: Piața Mocioni</span><span className="block text-muted-foreground">Treceri fără oprire și minutele adăugate de ocolire, din înregistrare.</span></span>
            <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
          </a>
        )}
        <Folds><Fold id="method" title="Cum verificăm"><p className="leading-relaxed text-muted-foreground">{live.data.method.ro}</p></Fold></Folds>
      </>
    );
  }

  const d = cost.data;
  const measured = (d?.stretches ?? []).filter((x) => x.measured?.conclusive && x.measured.sec != null);
  const mmss = (sec: number | null | undefined) => (sec == null ? "–" : `${fmt.format(Math.round(sec / 6) / 10)} min`);
  return (
    <>
      <p className="text-[1.05rem] font-medium leading-snug">
        {s.stopsServedAnyway === 0
          ? `Niciun vehicul nu a oprit în stațiile suspendate: ${count(s.stopsSkipped ?? 0, "trecere", "treceri")} fără oprire.`
          : `${count(s.stopsServedAnyway ?? 0, "oprire", "opriri")} în stații suspendate, din ${fmt.format((s.stopsSkipped ?? 0) + (s.stopsServedAnyway ?? 0))} treceri.`}
      </p>
      <dl className="mt-5 grid grid-cols-3 gap-4">
        <Stat value={fmt.format(s.stopsSkipped ?? 0)} label="treceri fără oprire" />
        <Stat value={fmt.format(s.stopsServedAnyway ?? 0)} label="opriri totuși" />
        <Stat value={fmt.format(s.stopsUnknown ?? 0)} label="necunoscute" />
      </dl>
      <div className="mt-4"><Kind k="measured" detail={`${count(s.vehiclesSeen, "vehicul", "vehicule")}${live.data.label ? `, ${live.data.label.ro}` : ""}`} /></div>

      <Section title="Ocolirea: în orar, pe stradă, în estimarea noastră">
        {cost.error ? <p className="text-sm text-muted-foreground">Costul ocolirii nu e disponibil pentru această lucrare.</p> : !d ? (
          <><Loading rows={2} /><p className="mt-2 text-xs text-muted-foreground">Se calculează din înregistrare; durează câteva secunde.</p></>
        ) : d.status !== "ok" || measured.length === 0 ? (
          <p className="text-sm text-muted-foreground">Prea puține curse înregistrate pentru o măsurătoare.</p>
        ) : (
          <>
            {d.finding && <Long text={d.finding.ro} />}
            <table className="mt-4 w-full table-fixed text-left text-sm">
              <thead className="text-xs text-muted-foreground"><tr><th className="pb-2 font-medium">Porțiunea nouă</th><th className="w-[4.1rem] pb-2 text-right font-medium">Orar</th><th className="w-[4.6rem] pb-2 text-right font-medium">Măsurat</th><th className="w-[4.4rem] pb-2 text-right font-medium">Estimat</th></tr></thead>
              <tbody className="tabular divide-y">
                {measured.slice(0, 5).map((x) => (
                  <tr key={`${x.routeId}${x.directionId}${x.after.stopNames[0]}`}>
                    <td className="py-2 pr-2"><span className="flex min-w-0 items-center gap-2"><LineBadge routeId={x.routeId} label={x.shortName} /><span className="min-w-0 truncate" title={x.after.stopNames.join(" → ")}>{x.after.stopNames[0]}</span></span></td>
                    <td className="whitespace-nowrap py-2 text-right text-muted-foreground">{mmss(x.planned.after.sec)}</td>
                    <td className="whitespace-nowrap py-2 text-right font-semibold">{mmss(x.measured!.sec)}</td>
                    <td className="whitespace-nowrap py-2 text-right text-muted-foreground">{mmss(x.estimated?.sec)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {d.totals?.estimateError.sec != null && (
              <p className="tabular mt-3 text-sm leading-relaxed">
                Estimarea platformei a greșit cu <span className="font-semibold">{minutes(d.totals.estimateError.sec)}</span> pe cursă, pe {count(d.totals.estimateError.n, "cursă", "curse")} pe care nu le văzuse.
              </p>
            )}
            <div className="mt-3"><Kind k="measured" detail={d.label.ro} /></div>
            <Method>Doar vineri după-amiază și weekend, fără extrapolare la zile lucrătoare. Estimare din datele live, nu raportul oficial.</Method>
          </>
        )}
      </Section>

      <Folds><Fold id="method" title="Cum verificăm"><p className="leading-relaxed text-muted-foreground">{live.data.method.ro}</p></Fold></Folds>
    </>
  );
}
