// R6-F: per line, the share of recorded trips run by a vehicle the City Hall feed flags step-free, with n.
// Sorted by trips without such a vehicle, so STPT sees first where a low-floor vehicle would change most.
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { accessibility, type AccessibilityLines, type AccessibleLine, type HourShare } from "../../api/accessibility";
import { Figure } from "../../components/Figure";
import { LoadState } from "../../components/Panel";
import { tr } from "../../lib/format";
import { useResource } from "../../lib/store";
import { S } from "./strings";
import "./accessible.css";

const FIRST = 8;
const HOURS = Array.from({ length: 24 }, (_, h) => h);
const missing = (l: AccessibleLine) => Math.max(0, l.trips - l.unknown - l.stepFree);

export function AccessibleLines() {
  useTranslation();
  const res = useResource<AccessibilityLines>("accessibility:lines", () => accessibility.lines());
  const [all, setAll] = useState(false);
  const d = res.data;
  if (!d) return <LoadState loading={res.loading} error={res.error} />;

  const rows = [...d.lines].sort((a, b) => missing(b) - missing(a) || b.trips - a.trips);
  const shown = all ? rows : rows.slice(0, FIRST);
  const perHour = d.lines.flatMap((l) => l.hours.map((h) => h.trips)).filter((n) => n > 0);

  return (
    <section className="acc" aria-labelledby="acc-title">
      <h3 id="acc-title">{tr(S.acc.title)}</h3>
      <p className="small">
        <Figure inline value={d.trips.share == null ? null : d.trips.share * 100} unit="%" digits={1} provenance={d.provenance} method={tr(d.method)} /> {tr(S.acc.knownShare)}{" "}
        <Figure inline value={d.trips.trips} provenance={d.provenance} method={tr(d.method)} /> {tr(S.acc.recordedTrips)}{" "}
        <span className="muted">{tr(d.recording.label)}.</span>
      </p>
      <p className="small muted">{tr(S.acc.order)}</p>

      <table className="table acc-table">
        <thead>
          <tr>
            <th scope="col">{tr(S.acc.line)}</th>
            <th scope="col" className="num">{tr(S.acc.share)}</th>
            <th scope="col" className="num">{tr(S.acc.n)}</th>
            <th scope="col">{tr(S.acc.hours)}</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((l) => (
            <tr key={l.routeId}>
              <td>
                <span className="line-chip">{l.shortName}</span>
              </td>
              <td className="num"><Figure inline value={l.share == null ? null : l.share * 100} unit="%" provenance={d.provenance} method={tr(d.method)} /></td>
              <td className="num"><Figure inline value={l.trips} provenance={d.provenance} method={tr(d.method)} /></td>
              <td>
                <HourStrip line={l.shortName} hours={l.hours} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > FIRST && (
        <button type="button" className="linklike small acc-more" aria-expanded={all} onClick={() => setAll(!all)}>
          {all ? tr(S.acc.fewer) : tr(S.acc.all)}
        </button>
      )}
      <p className="small muted">
        {tr(S.acc.legend)} {tr(S.acc.sampleRange)}{" "}
        <Figure inline value={perHour.length ? Math.min(...perHour) : null} provenance={d.provenance} />–<Figure inline value={perHour.length ? Math.max(...perHour) : null} provenance={d.provenance} /> {tr(S.acc.n).toLocaleLowerCase()}.
      </p>
      <p className="small muted">{tr(d.caveat)}</p>
    </section>
  );
}

/** 24 cells, one per local hour; fill = share of step-free trips, no cell = no recorded trip. */
function HourStrip({ line, hours }: { line: string; hours: HourShare[] }) {
  const byHour = new Map(hours.map((h) => [h.hour, h]));
  const said = hours.map((h) => `${h.hour}: ${h.share == null ? tr(S.acc.unknownHour) : `${h.stepFree}/${h.trips}`}`).join(", ");
  return (
    <span className="acc-strip" role="img" aria-label={`${tr(S.acc.stripLabel).replace("{line}", line)} ${said}`}>
      {HOURS.map((hour) => {
        const h = byHour.get(hour);
        if (!h || h.trips === 0) return <span key={hour} className="acc-cell acc-none" />;
        if (h.share == null) return <span key={hour} className="acc-cell acc-unknown" title={`${String(hour).padStart(2, "0")}:00 · ${tr(S.acc.unknownHour)}`} />;
        const pct = Math.round(h.share * 100);
        return (
          <span
            key={hour}
            className="acc-cell"
            style={{ background: `color-mix(in srgb, var(--c-accent) ${pct}%, var(--c-bg))` }}
            title={`${String(hour).padStart(2, "0")}:00 · ${h.stepFree}/${h.trips}`}
          />
        );
      })}
    </span>
  );
}
