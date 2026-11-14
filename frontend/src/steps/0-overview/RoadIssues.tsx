// R19: a repair-priority list from two real city datasets, not an inspection of the road surface.
import { useTranslation } from "react-i18next";
import type { RoadIssues as Issues } from "../../api/roadIssues";
import { Figure } from "../../components/Figure";
import { LoadState } from "../../components/Panel";
import { fmtDate, fmtWindow, tr } from "../../lib/format";
import { invalidate, type Resource } from "../../lib/store";
import { S } from "./strings";

function count(n: number | null | undefined): number | null {
  return typeof n === "number" && Number.isFinite(n) ? n : null;
}

function place(name: string | null | undefined, unknown: string) {
  const text = name?.trim();
  return text ? text : unknown;
}

export function RoadIssues({ result }: { result: Resource<Issues> }) {
  const { t } = useTranslation();
  const r = result.data;
  const text = S.roadIssues;
  const recorded = r?.recorded?.start && r.recorded.end ? fmtWindow({ start: r.recorded.start, end: r.recorded.end }) : null;
  return (
    <section className="road-issues" aria-label={tr(text.title)}>
      <h3>{tr(text.title)}</h3>
      {!r ? <>
        <LoadState loading={result.loading} error={result.error} />
        {result.error && <button type="button" className="btn" onClick={() => invalidate("roadIssues")}>{tr(text.retry)}</button>}
      </> : <>
        <p className="small">
          <Figure inline value={count(r.segmentsWithReports)} provenance={r.provenance} /> {tr(text.segments)} ·{" "}
          <Figure inline value={count(r.potholesOnCorridors)} provenance={r.provenance} /> {tr(text.reports)}
        </p>
        {r.segments.length === 0 ? <p className="small muted">{tr(text.empty)}</p> : <>
          <p className="small muted">{tr(text.top)}</p>
          <ul className="list small">
            {r.segments.slice(0, 5).map((segment) => <li key={segment.segmentId}>
              <strong>{place(segment.fromName, t("unknown"))} → {place(segment.toName, t("unknown"))}</strong><br />
              <Figure inline value={count(segment.potholes)} provenance={r.provenance} /> {tr(text.reports)} ·{" "}
              <Figure inline value={count(segment.departuresPerDay)} provenance={r.provenance} /> {tr(text.departures)}
            </li>)}
          </ul>
        </>}
        <p className="small muted">{tr(text.recorded)} {recorded ?? t("unknown")}; {tr(text.countsOnly)}.</p>
        <p className="small muted">{tr(text.planned)} {r.departuresDay ? fmtDate(r.departuresDay) : t("unknown")}. {tr(text.basis)} <Figure inline value={count(r.matchMeters)} unit="m" provenance={r.provenance} />.</p>
      </>}
    </section>
  );
}
