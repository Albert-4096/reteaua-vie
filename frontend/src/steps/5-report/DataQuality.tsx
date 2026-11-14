// R12: gaps in the published inputs, their owner and a neutral data request.
import { useTranslation } from "react-i18next";
import { apiGet, type I18n, type Provenance } from "../../api/client";
import { Figure } from "../../components/Figure";
import { LoadState } from "../../components/Panel";
import { fmtDateTime, tr } from "../../lib/format";
import { invalidate, useResource } from "../../lib/store";
import "./dataQuality.css";

type QualityRow = {
  id: string;
  title: I18n;
  status: "de_verificat" | "in_regula" | "indisponibil";
  basis: "calculat" | "manual";
  found: number | null;
  of: number | null;
  detail: string[];
  owner: "SMTT" | "STPT" | "Primăria" | "Timpark";
  unlocks: I18n;
  request: I18n;
  provenance: Provenance[];
};
type Quality = { generatedAt: string; rows: QualityRow[]; provenance: Provenance[] };
const Q = {
  title: { ro: "Calitatea datelor publicate", en: "Published-data quality" },
  intro: { ro: "Ce trebuie verificat cu deținătorii datelor, pentru cifre mai precise în platformă și CityApp.", en: "What to check with the data owners for more precise figures in the platform and CityApp." },
  found: { ro: "Identificate", en: "Found" },
  of: { ro: "din", en: "of" },
  status: {
    de_verificat: { ro: "de verificat", en: "to check" },
    in_regula: { ro: "în regulă", en: "checked" },
    indisponibil: { ro: "indisponibil", en: "unavailable" },
  },
  basis: {
    calculat: { ro: "calculat din date", en: "calculated from data" },
    manual: { ro: "verificare manuală, datată", en: "dated manual check" },
  },
  details: { ro: "Ce deblochează și cererea de date", en: "What it unlocks and the data request" },
  request: { ro: "Cerere pregătită pentru deținătorul datelor", en: "Prepared request for the data owner" },
  export: { ro: "Descarcă fișa CSV", en: "Download the CSV sheet" },
  source: { ro: "Surse", en: "Sources" },
  generated: { ro: "Fișă calculată la", en: "Sheet generated at" },
  retry: { ro: "Reîncearcă", en: "Retry" },
  empty: { ro: "Nicio verificare returnată de sursă.", en: "The source returned no checks." },
};
const STATUS_CLASS = { de_verificat: "st-unsure", in_regula: "st-ok", indisponibil: "muted" } as const;

export function DataQuality() {
  useTranslation();
  const resource = useResource<Quality>("dataQuality", () => apiGet<Quality>("/api/data-quality"));
  const d = resource.data;
  return (
    <section className="data-quality" aria-label={tr(Q.title)}>
      <h2>{tr(Q.title)}</h2>
      <p className="small muted">{tr(Q.intro)}</p>
      {!d ? <>
        <LoadState loading={resource.loading} error={resource.error} />
        {resource.error && <button type="button" className="btn" onClick={() => invalidate("dataQuality")}>{tr(Q.retry)}</button>}
      </> : <>
        {d.rows.length === 0 ? <p className="small muted">{tr(Q.empty)}</p> : <ul className="list data-quality-rows">
          {d.rows.map((row) => <li key={row.id}>
            <h3>{tr(row.title)}</h3>
            <p className="small">
              <span className={STATUS_CLASS[row.status]}>{tr(Q.status[row.status])}</span> · {row.owner} · {tr(Q.basis[row.basis])}
            </p>
            <p className="small">
              {tr(Q.found)}: <Figure inline value={row.found} provenance={row.provenance} />
              {row.of !== null && <> {tr(Q.of)} <Figure inline value={row.of} provenance={row.provenance} /></>}
            </p>
            <details>
              <summary>{tr(Q.details)}</summary>
              <p className="small">{tr(row.unlocks)}</p>
              {row.detail.length > 0 && <ul className="small data-quality-detail">{row.detail.map((detail, i) => <li key={i}>{detail}</li>)}</ul>}
              <h4>{tr(Q.request)}</h4>
              <p className="small data-quality-request">{tr(row.request)}</p>
              <p className="small muted">{tr(Q.source)}: {row.provenance.map((p, i) => <span key={i}>
                {i > 0 && "; "}{p.url ? <a href={p.url} target="_blank" rel="noreferrer">{p.source}</a> : p.source}
                {p.version && ` ${p.version}`}{p.fetchedAt && `, ${fmtDateTime(p.fetchedAt)}`}
              </span>)}</p>
            </details>
          </li>)}
        </ul>}
        <p className="small muted">{tr(Q.generated)} {fmtDateTime(d.generatedAt)}.</p>
        <a className="small" href="/api/data-quality.csv" download>{tr(Q.export)}</a>
      </>}
    </section>
  );
}
