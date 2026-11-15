import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LineBadge } from "@/landing/LineBadge";
import { useNetwork } from "@/lib/network";
import { cn } from "@/lib/utils";
import { count, fmt, type Analysis, type ClosureSummary, type DecisionGroup, type GeneratedNotice, type Impact as ImpactData } from "../../data";
import { lineShape, stretch, type Station } from "../../lines";
import { LineStrip, type Mark, type StripRow } from "../../LineStrip";
import { Fold, Folds, Kind, Loading, Problem, Section, Stat } from "../../ui";
import type { Answer, Focus } from "../Work";

const ACTION: Record<string, string> = { suspended: "Nu circulă", shortened: "Traseu scurtat", diverted: "Deviată" };

type Props = {
  c: ClosureSummary;
  analysis: Analysis | null;
  error: string | null;
  impact: ImpactData | null;
  notice: GeneratedNotice | null;
  answers: Map<string, Answer>;
  focus: Focus;
  setFocus: (f: Focus) => void;
  onHover: (s: Station | null) => void;
  onAnswer: (g: DecisionGroup, affected: boolean) => Promise<void>;
};

/** Who loses service: the answer as a sentence, what a person still has to decide, then line by line. */
export function Impact({ c, analysis, error, impact, notice, answers, focus, setFocus, onHover, onAnswer }: Props) {
  const net = useNetwork();
  const groups = analysis?.decisionGroups ?? [];
  const answered = groups.filter((g) => answers.get(g.id)).length;
  const t = impact?.totals;

  // one row per line: what the notice does to it and the stations it no longer serves
  const lines = useMemo(() => {
    const m = new Map<string, { routeId: string; action: string; closed: Set<string> }>();
    for (const s of notice?.sections ?? []) {
      const x = m.get(s.routeId) ?? { routeId: s.routeId, action: s.action, closed: new Set<string>() };
      s.stopsNotServed.forEach((st) => x.closed.add(st.stopId));
      m.set(s.routeId, x);
    }
    for (const r of c.routeIds) {
      if (m.has(r)) continue;
      const closed = new Set((analysis?.stops ?? []).filter((s) => s.routeId === r && (s.confirmed ?? s.state === "affected")).map((s) => s.stopId));
      m.set(r, { routeId: r, action: c.routeActions?.find((a) => a.routeId === r)?.action ?? "diverted", closed });
    }
    return [...m.values()];
  }, [notice, analysis, c]);

  if (error) return <Problem>Analiza lucrării nu s-a încărcat ({error}). Reîncărcați pagina.</Problem>;
  if (!analysis || !t) return <Loading rows={4} />;

  const waiting = groups.length - answered;
  // what a person still has to decide comes first; once decided, the answer leads and the decisions rest below it
  const decide = groups.length > 0 && (
    <Section title={answered === groups.length ? "Hotărât de un om" : "De hotărât"} aside={answered === groups.length ? `${answered} din ${groups.length}` : `răspuns la ${answered} din ${groups.length}`}>
      <p className="-mt-1 mb-3 text-sm leading-snug text-muted-foreground">{answered === groups.length ? "Anunțul nu spune tot. Unde nu am putut ști, am întrebat un om." : "Anunțul nu spune tot. Unde nu putem ști, întrebăm un om."}</p>
      <ul className="space-y-2.5">
        {groups.map((g) => (
          <Question key={g.id} g={g} answer={answers.get(g.id) ?? null} open={focus?.kind === "question" && focus.id === g.id}
            onToggle={(o) => setFocus(o ? { kind: "question", id: g.id } : null)} onAnswer={onAnswer} onHover={onHover} />
        ))}
      </ul>
    </Section>
  );

  return (
    <>
      {waiting > 0 && decide}
      <section className={waiting > 0 ? "mt-8" : undefined}>
        <p className="text-[1.05rem] font-medium leading-snug">{changes(lines, (id) => net?.byId.get(id)?.shortName ?? id.replace(/^R_[A-Z]+_/, ""))}</p>
        <dl className="mt-5 grid grid-cols-3 gap-4">
          <Stat value={fmt.format(t.stopsSuspended)} label={t.stopsSuspended === 1 ? "stație fără niciun serviciu" : "stații fără niciun serviciu"} tone={t.stopsSuspended > 0 ? "closure" : undefined} />
          <Stat value={fmt.format(t.departuresLost)} label="plecări pierdute" />
          {t.residentsLosingStop != null && <Stat value={fmt.format(t.residentsLosingStop)} label="locuitori la peste 400 m de o stație" />}
        </dl>
        <div className="mt-4"><Kind k="estimate" detail="orarul SMTT și modelul de populație GHSL 2020" /></div>
        {waiting > 0 && <p className="mt-2.5 text-sm text-muted-foreground">Fără stațiile încă nehotărâte; cifrele cresc sau rămân după răspuns.</p>}
      </section>
      {waiting === 0 && decide}

      <Section title="Ce se schimbă pe fiecare linie">
        <ul className="-mx-2">
          {lines.map((l) => {
            const shape = net && lineShape(net, l.routeId);
            const rows: StripRow[] = (shape?.stations ?? []).map((s) => ({ station: s, mark: s.ids.some((x) => l.closed.has(x)) ? "closed" : "served" }));
            const lost = rows.filter((r) => r.mark === "closed").length;
            const on = focus?.kind === "line" && focus.routeId === l.routeId;
            return (
              <li key={l.routeId}>
                <button type="button" aria-expanded={on} onClick={() => setFocus(on ? null : { kind: "line", routeId: l.routeId })}
                  className={cn("flex w-full items-center gap-3 rounded-lg px-2 py-2.5 text-left outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring", on && "bg-muted")}>
                  <LineBadge routeId={l.routeId} size="lg" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">{ACTION[l.action] ?? "Afectată"}</span>
                    <span className="tabular block text-sm text-muted-foreground">{rows.length ? `nu oprește în ${lost} din ${count(rows.length, "stație", "stații")}` : "traseul nu e disponibil"}</span>
                  </span>
                  <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform duration-200", on && "rotate-180")} />
                </button>
                {on && rows.length > 0 && <LineStrip className="mb-3 ml-2 mt-1" color={`#${net?.byId.get(l.routeId)?.color ?? "888888"}`} rows={rows} onHover={onHover} />}
              </li>
            );
          })}
          {(c.temporaryRoutes ?? []).map((tr, i) => {
            const on = focus?.kind === "temp" && focus.index === i;
            return (
              <li key={tr.shortName}>
                <button type="button" aria-pressed={on} onClick={() => setFocus(on ? null : { kind: "temp", index: i })}
                  className={cn("flex w-full items-start gap-3 rounded-lg px-2 py-2.5 text-left outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring", on && "bg-muted")}>
                  <span className="tabular inline-flex h-9 min-w-9 items-center justify-center rounded-md border border-dashed border-foreground/50 px-2 text-sm font-semibold">{tr.shortName}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">Linie temporară, {tr.mode === "bus" ? "autobuz" : tr.mode}</span>
                    <span className="line-clamp-2 text-sm text-muted-foreground">{tr.streets.join(" · ")}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </Section>

      <Folds>
        {impact.byZone.length > 0 && (
          <Fold id="zones" title="Pe cartiere" aside={impact.byZone.length}>
            <table className="w-full text-left">
              <thead className="text-xs text-muted-foreground"><tr><th className="pb-2 font-medium">Cartier</th><th className="whitespace-nowrap pb-2 pl-4 text-right font-medium">Stații</th><th className="whitespace-nowrap pb-2 pl-4 text-right font-medium">Plecări</th><th className="whitespace-nowrap pb-2 pl-4 text-right font-medium">Locuitori</th></tr></thead>
              <tbody className="tabular divide-y">
                {impact.byZone.map((z) => (
                  <tr key={z.slug}><td className="py-2 pr-2">{z.name}</td><td className="whitespace-nowrap py-2 pl-4 text-right">{z.stopsSuspended}</td><td className="whitespace-nowrap py-2 pl-4 text-right">{fmt.format(z.departuresLost)}</td><td className="whitespace-nowrap py-2 pl-4 text-right">{z.residentsLosingStop == null ? "necunoscut" : fmt.format(z.residentsLosingStop)}</td></tr>
                ))}
              </tbody>
            </table>
          </Fold>
        )}
        <Fold id="method" title="Cum calculăm"><p className="leading-relaxed text-muted-foreground">{impact.method.ro}</p></Fold>
      </Folds>
    </>
  );
}

/** What the works do to the lines, in one sentence: "Linia 4 nu circulă; liniile 2 și 7 circulă pe trasee scurtate." */
function changes(lines: { routeId: string; action: string }[], name: (routeId: string) => string) {
  const by = new Map<string, string[]>();
  for (const l of lines) by.set(l.action, [...(by.get(l.action) ?? []), name(l.routeId)]);
  const list = (xs: string[]) => (xs.length === 1 ? `linia ${xs[0]}` : `liniile ${xs.slice(0, -1).join(", ")} și ${xs[xs.length - 1]}`);
  const say: Record<string, [string, string]> = {
    suspended: ["nu circulă", "nu circulă"],
    shortened: ["circulă pe traseu scurtat", "circulă pe trasee scurtate"],
    diverted: ["ocolește lucrarea", "ocolesc lucrarea"],
  };
  const parts = [...by].map(([action, xs]) => `${list(xs)} ${(say[action] ?? ["este afectată", "sunt afectate"])[xs.length === 1 ? 0 : 1]}`);
  const text = parts.join("; ");
  return text ? `${text[0].toUpperCase()}${text.slice(1)}.` : "Nicio linie nu este afectată.";
}

/**
 * One question for a person. It never stands alone: the line is drawn station by station with the
 * asked stretch marked, and the map frames the same stretch with its ends named.
 */
function Question({ g, answer, open, onToggle, onAnswer, onHover }: { g: DecisionGroup; answer: Answer; open: boolean; onToggle: (open: boolean) => void; onAnswer: Props["onAnswer"]; onHover: Props["onHover"] }) {
  const net = useNetwork();
  const [busy, setBusy] = useState<boolean | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const card = useRef<HTMLLIElement>(null);
  useEffect(() => { if (open) card.current?.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }); }, [open]);
  const shape = net && lineShape(net, g.routeId);
  const st = shape && stretch(shape, new Set(g.rows.map((r) => r.stopId)));
  const mark: Mark = answer === "affected" ? "closed" : answer === "served" ? "served" : "ask";
  const rows: StripRow[] = (shape?.stations ?? []).map((s, i) => ({ station: s, mark: st && i >= st.first && i <= st.last ? mark : "plain" }));
  const n = st ? st.last - st.first + 1 : g.rows.length;
  const said = answer === "affected" ? `Nu oprește. ${count(n, "stație intră", "stații intră")} în alertă.` : answer === "served" ? `Oprește. ${count(n, "stație rămâne deservită", "stații rămân deservite")}.` : null;

  const pick = async (affected: boolean) => {
    setBusy(affected); setErr(null);
    try { await onAnswer(g, affected); } catch (e) { setErr(`Răspunsul nu s-a salvat (${(e as Error).message}). Încercați din nou.`); } finally { setBusy(null); }
  };

  if (!open) {
    return (
      <li>
        <button type="button" aria-expanded={false} onClick={() => onToggle(true)}
          className="flex w-full items-start gap-3 rounded-xl border px-4 py-3 text-left outline-none transition-colors hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring">
          {answer
            ? <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground"><Check className="size-3" strokeWidth={3} /></span>
            : <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full border-2 border-foreground"><span className="size-1.5 rounded-full bg-foreground" /></span>}
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-medium leading-snug">{g.question.ro}</span>
            <span className={cn("mt-0.5 block text-sm", answer ? "text-muted-foreground" : "text-foreground")}>
              {said ? <><span className="font-medium text-foreground">Răspuns dat:</span> {said[0].toLowerCase() + said.slice(1)}</> : "Așteaptă un răspuns."}
            </span>
          </span>
          <ChevronDown className="mt-1 size-4 shrink-0 text-muted-foreground" />
        </button>
      </li>
    );
  }

  return (
    <li ref={card} className="scroll-my-4 rounded-xl border border-foreground/25 bg-card px-4 pb-4 pt-3.5 shadow-card">
      <div className="flex items-start gap-3">
        <p className="min-w-0 flex-1 text-base font-semibold leading-snug">{g.question.ro}</p>
        <button type="button" onClick={() => onToggle(false)} aria-label="Închide întrebarea"
          className="-mr-1.5 -mt-0.5 grid size-7 shrink-0 place-items-center rounded-md text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"><X className="size-4" /></button>
      </div>
      {rows.length > 0 && (
        <div className="mt-3 rounded-lg bg-muted/60 px-3 py-2.5">
          <p className="mb-1.5 flex items-center gap-2 text-xs text-muted-foreground"><LineBadge routeId={g.routeId} /> Traseul liniei. Porțiunea întrebată e încadrată pe hartă.</p>
          <LineStrip color={`#${net?.byId.get(g.routeId)?.color ?? "888888"}`} rows={rows} onHover={onHover} />
        </div>
      )}
      <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{g.reason.ro}</p>

      {!answer && g.suggested === "affected" && <p className="mt-4 text-sm text-accent-foreground">Propunerea platformei: nu oprește.</p>}
      <div className={cn("grid grid-cols-2 gap-2", !answer && g.suggested === "affected" ? "mt-2" : "mt-4")}>
        {([true, false] as const).map((affected) => {
          const chosen = answer === (affected ? "affected" : "served");
          const lead = chosen || (!answer && affected && g.suggested === "affected");
          return (
            <Button key={String(affected)} disabled={busy !== null} variant={lead ? "default" : "outline"} aria-pressed={chosen} onClick={() => pick(affected)} className="h-10 rounded-lg">
              {chosen && <Check className="size-4" />}{busy === affected ? "Se salvează…" : affected ? "Nu oprește" : "Oprește"}
            </Button>
          );
        })}
      </div>
      {said && <p className="mt-2.5 text-sm text-muted-foreground">{said}</p>}
      {err && <p role="alert" className="mt-2.5 text-sm text-closure-ink">{err}</p>}
    </li>
  );
}
