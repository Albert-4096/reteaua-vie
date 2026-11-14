// L1: one summary in Decide, stretch details in Monitor. Signs are never turned into a claim of added delay.
import { useTranslation } from "react-i18next";
import { detourCost, type DetourCost as Cost, type Estimate } from "../api/detourCost";
import { tr } from "../lib/format";
import { invalidate, useResource } from "../lib/store";
import { Figure } from "./Figure";
import { LoadState } from "./Panel";
import "./detourCost.css";

const copy = {
  title: { ro: "Timp pe traseul modificat", en: "Time on the changed route" },
  planned: { ro: "Diferență în orar", en: "Timetable change" },
  measured: { ro: "Măsurat față de orar", en: "Measured versus timetable" },
  error: { ro: "Estimare față de măsurare", en: "Estimate versus measurement" },
  inconclusive: { ro: "neconcludent", en: "inconclusive" },
  samples: { ro: "curse", en: "trips" },
  limitation: { ro: "Doar vineri după-amiază și weekend; fără extrapolare la zilele lucrătoare.", en: "Friday afternoon and weekend only; do not extrapolate to weekdays." },
  details: { ro: "Tronsoane și intervale", en: "Stretches and intervals" },
  before: { ro: "Orar anterior", en: "Previous timetable" },
  after: { ro: "Orar în vigoare", en: "Current timetable" },
  actual: { ro: "Măsurat", en: "Measured" },
  estimated: { ro: "Estimat din alte linii", en: "Estimated from other lines" },
  interval: { ro: "Interval bootstrap 90%", en: "90% bootstrap interval" },
  none: {
    fara_inregistrare: { ro: "Necunoscut: nu există înregistrări pentru această fereastră.", en: "Unknown: no recording covers this window." },
    fara_orar_vechi: { ro: "Necunoscut: nu există un orar anterior pentru comparație.", en: "Unknown: no previous timetable is available for comparison." },
    fara_schimbare: { ro: "Orarul nu schimbă traseul în zona acestei închideri.", en: "The timetable does not change the route near this closure." },
  },
};

export function DetourCost({ closureId, detailed = false }: { closureId: string; detailed?: boolean }) {
  useTranslation();
  const key = `detourCost:${closureId}`;
  const result = useResource<Cost>(key, (onPending) => detourCost(closureId, onPending));
  const data = result.data;
  return (
    <section className="detour-cost" aria-label={tr(copy.title)}>
      <h2>{tr(copy.title)}</h2>
      {!data ? (
        <>
          <LoadState loading={result.loading} pending={result.pending} error={result.error} />
          {result.error && <button type="button" className="btn" onClick={() => invalidate(key)}>{tr({ ro: "Reîncearcă", en: "Retry" })}</button>}
        </>
      ) : data.status !== "ok" ? (
        <p className="small muted">{tr(copy.none[data.status])}</p>
      ) : (
        <>
          {data.finding && <p className="small">{tr(data.finding)}</p>}
          <dl className="detour-cost-values small">
            <dt>{tr(copy.planned)}</dt><dd><Minutes estimate={data.totals.plannedExtra} data={data} signed /></dd>
            <dt>{tr(copy.measured)}</dt><dd><Minutes estimate={data.totals.measuredVsPlanned} data={data} signed /></dd>
            <dt>{tr(copy.error)}</dt><dd><Minutes estimate={data.totals.estimateError} data={data} signed /></dd>
          </dl>
          {detailed && data.stretches.length > 0 && (
            <details>
              <summary>{tr(copy.details)}</summary>
              <ul className="list detour-cost-stretches">
                {data.stretches.map((s, index) => (
                  <li key={`${s.routeId}:${s.directionId}:${index}`}>
                    <h3>{s.shortName} · {s.after.stopNames[0]} → {s.after.stopNames.at(-1)}</h3>
                    <p className="small muted">{s.before.stopNames.join(" → ")} → {s.after.stopNames.join(" → ")}</p>
                    <dl className="detour-cost-values small">
                      <dt>{tr(copy.before)} {data.feedBefore}</dt><dd><Minutes estimate={s.planned.before} data={data} /></dd>
                      <dt>{tr(copy.after)} {data.feedAfter}</dt><dd><Minutes estimate={s.planned.after} data={data} /></dd>
                      <dt>{tr(copy.planned)}</dt><dd><Minutes estimate={s.planned.extra} data={data} signed /></dd>
                      <dt>{tr(copy.actual)}</dt><dd><Minutes estimate={s.measured} data={data} /></dd>
                      <dt>{tr(copy.measured)}</dt><dd><Minutes estimate={s.measuredVsPlanned} data={data} signed /></dd>
                      <dt>{tr(copy.estimated)}</dt><dd><Minutes estimate={s.estimated} data={data} /></dd>
                      <dt>{tr(copy.error)}</dt><dd><Minutes estimate={s.estimateError} data={data} signed /></dd>
                    </dl>
                  </li>
                ))}
              </ul>
              <p className="small muted">{tr(data.method)}</p>
            </details>
          )}
        </>
      )}
      {data?.label && <p className="small muted">{tr(data.label)} · {tr(copy.limitation)}</p>}
    </section>
  );
}

function Minutes({ estimate, data, signed = false }: { estimate: Estimate | null; data: Cost; signed?: boolean }) {
  const figure = (seconds: number | null | undefined) => (
    <>{signed && seconds != null && seconds > 0 ? "+" : ""}<Figure inline value={seconds == null ? null : seconds / 60} unit="min" digits={1} provenance={data.provenance} method={tr(data.method)} /></>
  );
  if (!estimate) return figure(null);
  return (
    <span>
      {figure(estimate.sec)}
      {!estimate.conclusive && <span> · {tr(copy.inconclusive)}</span>}
      <span className="detour-cost-interval muted">
        {tr(copy.interval)}: {figure(estimate.low)} – {figure(estimate.high)} · <Figure inline value={estimate.n} provenance={data.provenance} method={tr(data.method)} /> {tr(copy.samples)}
      </span>
    </span>
  );
}
