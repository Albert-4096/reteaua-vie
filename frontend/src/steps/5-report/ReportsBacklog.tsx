// R26: aggregate mobility reports from the City's existing channel, never report text or locations.
import { Fragment, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiGet, type I18n, type Provenance } from "../../api/client";
import { Figure } from "../../components/Figure";
import { LoadState } from "../../components/Panel";
import { fmtDate, fmtWindow, tr } from "../../lib/format";
import { invalidate, useResource } from "../../lib/store";
import "./reportsBacklog.css";

type AreaRow = {
  id: string;
  name: string;
  total: number;
  open: number;
  resolved: number;
  resolvedShare: number | null;
  oldestOpenAt: string | null;
  distinctProblems: number;
  departuresPerDay: number;
};
type AreaReports = {
  kind: "zones" | "stops";
  categories: string[];
  radiusMeters: number | null;
  departuresDay: string;
  recorded: { start: string; end: string };
  reportsRecorded: number;
  rows: AreaRow[];
  label: I18n;
  note: I18n;
  provenance: Provenance[];
};
const CATEGORIES = ["Transport în comun", "Trafic rutier și semne de circulație", "Străzi și trotuare"];
const B = {
  title: { ro: "Sesizări de mobilitate, pe cartiere", en: "Mobility reports by neighbourhood" },
  order: { ro: "Ordonate după sesizări deschise, apoi după plecările din orar.", en: "Ordered by open reports, then by timetable departures." },
  category: { ro: "Categoria sesizărilor", en: "Report category" },
  allCategories: { ro: "Toate categoriile de mobilitate", en: "All mobility categories" },
  recorded: { ro: "Înregistrate", en: "Recorded" },
  area: { ro: "Cartier", en: "Neighbourhood" },
  open: { ro: "Deschise", en: "Open" },
  age: { ro: "Vechime", en: "Age" },
  ageHint: { ro: "Cea mai veche sesizare deschisă din înregistrare, în zile", en: "Oldest recorded open report, in days" },
  ageMethod: { ro: "Zile între data celei mai vechi sesizări deschise înregistrate și sfârșitul înregistrării. Nu este vârsta întregului registru al Primăriei.", en: "Days from the oldest recorded open report to the recording end; not the age of the City's full backlog." },
  resolved: { ro: "Rezolvate", en: "Resolved" },
  days: { ro: "zile", en: "days" },
  details: { ro: "Probleme distincte și plecări în orar", en: "Distinct problems and timetable departures" },
  problems: { ro: "Probleme distincte", en: "Distinct problems" },
  problemMethod: { ro: "Aceeași categorie la cel mult 25 m, numărată o singură dată.", en: "The same category within 25 m is counted once." },
  departures: { ro: "Plecări din orarul GTFS", en: "GTFS timetable departures" },
  all: { ro: "Arată toate cartierele", en: "Show all neighbourhoods" },
  fewer: { ro: "Arată doar primele cartiere", en: "Show the first neighbourhoods" },
  export: { ro: "Descarcă sesizările pe cartiere (CSV)", en: "Download neighbourhood report counts (CSV)" },
  empty: { ro: "Nicio sesizare înregistrată în această categorie.", en: "No report was recorded in this category." },
  retry: { ro: "Reîncearcă", en: "Retry" },
};

function ageDays(oldest: string | null, until: string): number | null {
  if (!oldest) return null;
  const days = (Date.parse(until) - Date.parse(oldest)) / 86_400_000;
  return Number.isFinite(days) && days >= 0 ? days : null;
}

export function ReportsBacklog() {
  useTranslation();
  const categoryId = useId();
  const [category, setCategory] = useState("all");
  const [all, setAll] = useState(false);
  const query = `?category=${encodeURIComponent(category)}`;
  const key = `reportsBacklog:${category}`;
  const result = useResource<AreaReports>(key, () => apiGet<AreaReports>(`/api/reports/zones${query}`));
  const data = result.data;
  const shown = all ? data?.rows : data?.rows.slice(0, 8);
  return (
    <section className="reports-backlog" aria-label={tr(B.title)}>
      <h2>{tr(B.title)}</h2>
      <label className="small" htmlFor={categoryId}>{tr(B.category)}</label>
        <select id={categoryId} value={category} onChange={(e) => { setCategory(e.target.value); setAll(false); }}>
          <option value="all">{tr(B.allCategories)}</option>
          {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      {!data ? <>
        <LoadState loading={result.loading} error={result.error} />
        {result.error && <button type="button" className="btn" onClick={() => invalidate(key)}>{tr(B.retry)}</button>}
      </> : <>
        <p className="small muted">{tr(data.label)} · {fmtWindow(data.recorded)}</p>
        <p className="small">{tr(B.recorded)}: <Figure inline value={data.reportsRecorded} provenance={data.provenance} />. {tr(B.order)}</p>
        {data.rows.length === 0 ? <p className="small muted">{tr(B.empty)}</p> : <>
          <table className="table reports-backlog-table">
            <thead><tr>
              <th scope="col">{tr(B.area)}</th>
              <th scope="col" className="num">{tr(B.open)}</th>
              <th scope="col" className="num" title={tr(B.ageHint)}>{tr(B.age)}</th>
              <th scope="col" className="num">{tr(B.resolved)}</th>
            </tr></thead>
            <tbody>{shown?.map((row) => <Fragment key={row.id}>
              <tr>
                <th scope="row">{row.name}</th>
                <td className="num"><Figure inline value={row.open} provenance={data.provenance} method={tr(data.note)} /></td>
                <td className="num"><Figure inline value={ageDays(row.oldestOpenAt, data.recorded.end)} digits={1} unit={tr(B.days)} provenance={data.provenance} method={tr(B.ageMethod)} /></td>
                <td className="num"><Figure inline value={row.resolvedShare === null ? null : row.resolvedShare * 100} unit="%" provenance={data.provenance} method={tr(data.note)} /></td>
              </tr>
              <tr className="reports-backlog-detail"><td colSpan={4}>
                <details><summary>{tr(B.details)}</summary>
                  <p className="small">{tr(B.problems)}: <Figure inline value={row.distinctProblems} provenance={data.provenance} method={tr(B.problemMethod)} /></p>
                  <p className="small">{tr(B.departures)} ({fmtDate(data.departuresDay)}): <Figure inline value={row.departuresPerDay} provenance={data.provenance} /></p>
                </details>
              </td></tr>
            </Fragment>)}</tbody>
          </table>
          {data.rows.length > 8 && <button type="button" className="linklike small" aria-expanded={all} onClick={() => setAll(!all)}>{tr(all ? B.fewer : B.all)}</button>}
        </>}
        <p className="small muted">{tr(data.note)}</p>
        <a className="small" href={`/api/reports/zones.csv${query}`} download>{tr(B.export)}</a>
      </>}
    </section>
  );
}
