// L2-F: the measured window order. Departures and vehicle-minutes stay separate numbers.
import { measuredWindows, type MeasuredWindow, type MeasuredWindowsReport } from "../../api/measuredWindows";
import { Figure } from "../../components/Figure";
import { LoadState } from "../../components/Panel";
import { fmtWindow, tr } from "../../lib/format";
import { useResource } from "../../lib/store";

const C = {
  title: { ro: "Ferestre după traficul măsurat", en: "Windows by measured traffic" },
  lost: { ro: "plecări pierdute", en: "departures lost" },
  minutes: { ro: "minute de vehicul", en: "vehicle-minutes" },
  adds: { ro: "ocolirea adaugă", en: "the detour adds" },
  interval: { ro: "interval", en: "interval" },
  inconclusive: { ro: "neconcludent", en: "inconclusive" },
};

export function MeasuredWindows({ closureId }: { closureId: string }) {
  const res = useResource<MeasuredWindowsReport>(`measuredWindows:${closureId}:8`, (onPending) =>
    measuredWindows(closureId, onPending),
  );
  const r = res.data;
  const showOrder = r?.status === "ok" && r.candidates.length > 0;
  return (
    <section>
      <h2>{tr(C.title)}</h2>
      {!r ? (
        <LoadState loading={res.loading} pending={res.pending} error={res.error} />
      ) : (
        <>
          {r.label && (
            <p className="small muted" style={{ marginTop: "var(--sp-2)" }}>
              {tr(r.label)}
            </p>
          )}
          {!showOrder && r.note && <p style={{ marginTop: "var(--sp-2)" }}>{tr(r.note)}</p>}
          {showOrder && (
            <ul className="list" style={{ marginTop: "var(--sp-2)" }}>
              {r.candidates.map((row) => (
                <li key={`${row.rank}:${row.window.start}`}>
                  <strong>{row.rank}.</strong> {fmtWindow(row.window)}
                  <p className="small" style={{ marginTop: "var(--sp-1)" }}>
                    <Figure inline value={row.departuresLost} provenance={r.provenance} method={tr(r.method)} /> {tr(C.lost)}
                  </p>
                  <MinuteLine row={row} report={r} />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

function MinuteLine({ row, report }: { row: MeasuredWindow; report: MeasuredWindowsReport }) {
  const method = tr(report.method);
  const minute = (value: number | null) => (
    <Figure inline value={value} unit="min" digits={1} provenance={report.provenance} method={method} />
  );
  const positive = row.detourMinutes != null && row.detourMinutes > 0;
  const band = row.detourMinutesLow != null || row.detourMinutesHigh != null;
  return (
    <p className="small" style={{ marginTop: "var(--sp-1)" }}>
      {positive ? (
        <>
          {tr(C.adds)} {minute(row.detourMinutes)}
        </>
      ) : (
        <>
          {tr(C.minutes)} {minute(row.detourMinutes)}
        </>
      )}
      {band && (
        <span className="muted">
          {" ("}
          {tr(C.interval)} {minute(row.detourMinutesLow)}–{minute(row.detourMinutesHigh)}
          {")"}
        </span>
      )}
      {!row.conclusive && <> · {tr(C.inconclusive)}</>}
    </p>
  );
}
