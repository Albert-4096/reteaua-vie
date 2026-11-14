// R4: a person's assessment of a recorded window. Only confirmation can reach CityApp.
import { useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { apiSend, type I18n } from "../../api/client";
import { Figure } from "../../components/Figure";
import { fmtDateTime, tr } from "../../lib/format";
import { invalidate, setData } from "../../lib/store";
import { MISSING_CASE, type MissingLines, type MissingRoute } from "./missing";
import "./missingTriage.css";

export type TriageChoice = "confirmat" | "respins" | "nu_stiu";
type Reason = "dispozitiv_bord" | "linie_neoperata" | "trafic_lucrari_vreme" | "gol_date";
export type TriageDecision = {
  id: string;
  routeId: string;
  decision: TriageChoice;
  reason: Reason | null;
  who: string;
  decidedAt: string;
};
const choices: Record<TriageChoice, I18n> = {
  confirmat: { ro: "Confirm", en: "Confirm" },
  respins: { ro: "Resping", en: "Reject" },
  nu_stiu: { ro: "Nu știu", en: "Don't know" },
};
const reasons: Record<Reason, I18n> = {
  dispozitiv_bord: { ro: "Dispozitiv de bord", en: "Onboard device" },
  linie_neoperata: { ro: "Linie neoperată", en: "Line not operating" },
  trafic_lucrari_vreme: { ro: "Trafic, lucrări sau vreme", en: "Traffic, works or weather" },
  gol_date: { ro: "Gol în date", en: "Data gap" },
};
const unknownReason = { ro: "Motiv necunoscut", en: "Reason unknown" };

export function MissingTriage({ row, data }: { row: MissingRoute; data: MissingLines }) {
  useTranslation();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<TriageDecision | null>(row.decision ?? null);
  const d = saved;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    const form = event.currentTarget;
    const button = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const choice = button?.value as TriageChoice | undefined;
    if (!choice || !(choice in choices)) return;
    const values = new FormData(form);
    const who = String(values.get("who") ?? "").trim();
    if (who.length < 2) { setError(tr({ ro: "Alegeți rolul persoanei care verifică, fără nume personal.", en: "Enter the reviewing person's role, without a personal name." })); return; }
    pending.current = true; setBusy(true); setError(null);
    try {
      const result = await apiSend<TriageDecision>("PATCH", `/api/live/missing/${encodeURIComponent(row.routeId)}`, {
        window: data.window,
        decision: choice,
        reason: values.get("reason") || null,
        who,
        note: null,
      });
      setSaved(result);
      setData(`missing:${MISSING_CASE}`, { ...data, routes: data.routes.map((r) => r.routeId === row.routeId ? { ...r, decision: result } : r) });
      invalidate("overview", "linesStatus", "lineStatusRow:", "stopStatus:");
      setOpen(false);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { pending.current = false; setBusy(false); }
  }
  return (
    <div className="missing-triage">
      {row.repeatedDays != null && row.repeatedDays > 1 && <p className="small">
        {tr({ ro: "Repetat în", en: "Repeated on" })} <Figure inline value={row.repeatedDays} provenance={data.provenance} /> {tr({ ro: "zile înregistrate", en: "recorded days" })}
      </p>}
      {d && <p className="small" role="status">
        {tr({ ro: "Verificat în platformă", en: "Reviewed in the platform" })}: {tr(choices[d.decision])} · {d.reason ? tr(reasons[d.reason]) : tr(unknownReason)} · {d.who} · {fmtDateTime(d.decidedAt)}
      </p>}
      <button type="button" className="linklike small" aria-expanded={open} onClick={() => setOpen(!open)}>
        {tr({ ro: "Verifică această constatare", en: "Review this finding" })}
      </button>
      {open && <form onSubmit={submit} className="missing-triage-form">
        <p className="small muted">{tr({ ro: "Numai «Confirm» poate ajunge în CityApp. Constatarea nu este o confirmare oficială STPT.", en: "Only Confirm may reach CityApp. This finding is not an official STPT confirmation." })}</p>
        <fieldset disabled={busy}>
          <legend className="visually-hidden">{tr({ ro: "Verificarea constatării", en: "Finding review" })}</legend>
          <label>{tr({ ro: "Rol, fără nume personal", en: "Role, without a personal name" })}
            <input name="who" required minLength={2} maxLength={60} defaultValue={d?.who ?? ""} autoComplete="off" />
          </label>
          <label>{tr({ ro: "Motiv", en: "Reason" })}
            <select name="reason" defaultValue={d?.reason ?? ""}>
              <option value="">{tr(unknownReason)}</option>
              {Object.entries(reasons).map(([value, label]) => <option key={value} value={value}>{tr(label)}</option>)}
            </select>
          </label>
          <div className="missing-triage-actions">
            {(Object.keys(choices) as TriageChoice[]).map((choice) => <button type="submit" className="btn" name="decision" value={choice} key={choice}>{tr(choices[choice])}</button>)}
          </div>
        </fieldset>
        {busy && <p className="small" role="status">{tr({ ro: "Se salvează…", en: "Saving…" })}</p>}
        {error && <p className="error-msg" role="alert">{error}</p>}
      </form>}
    </div>
  );
}

export function MissingLogLink() {
  useTranslation();
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  return <section className="missing-triage">
    <h3>{tr({ ro: "Registrul verificărilor de dispecerat", en: "Dispatch review log" })}</h3>
    <label>{tr({ ro: "Luna", en: "Month" })} <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} /></label>
    {/^\d{4}-\d{2}$/.test(month) && <a href={`/api/live/missing/log.csv?month=${encodeURIComponent(month)}`}>
      {tr({ ro: "Descarcă deciziile pentru SMTT (CSV)", en: "Download decisions for SMTT (CSV)" })}
    </a>}
  </section>;
}
