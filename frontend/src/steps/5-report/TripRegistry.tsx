// R14-F: the latest day of the trip registry. Counts from the response only; kmEstimated stays labelled „estimare”.
import { Fragment, useState } from "react";
import { useTranslation } from "react-i18next";
import { registry, type RegistryDays, type RegistryEntry } from "../../api/registry";
import { Figure } from "../../components/Figure";
import { LoadState } from "../../components/Panel";
import { fmtDate, fmtDateTime, fmtWindow, tr } from "../../lib/format";
import { invalidate, useResource } from "../../lib/store";
import "./tripRegistry.css";

const FIRST = 8;
const HASH_PREFIX = 12;
const R = {
  title: { ro: "Registrul curselor", en: "Trip registry" },
  lines: { ro: "linii", en: "lines" },
  fingerprint: { ro: "amprentă", en: "fingerprint" },
  recording: { ro: "Înregistrare", en: "Recording" },
  health: { ro: "Sănătatea înregistrării", en: "Recording health" },
  until: { ro: "Comparat până la", en: "Compared until" },
  closed: { ro: "Zi închisă.", en: "Day closed." },
  openDay: { ro: "Ziua nu e închisă.", en: "The day is not closed." },
  compared: { ro: "Compararea cu orarul e completă.", en: "Timetable comparison is complete." },
  partial: { ro: "Compararea cu orarul nu e completă.", en: "Timetable comparison is not complete." },
  line: { ro: "Linie", en: "Line" },
  seen: { ro: "Văzute", en: "Seen" },
  share: { ro: "Pondere", en: "Share" },
  km: { ro: "km", en: "km" },
  estimate: { ro: "estimare", en: "estimate" },
  timetable: { ro: "Orar și înregistrare", en: "Timetable and recording" },
  scheduled: { ro: "În orar", en: "In the timetable" },
  inRecording: { ro: "În înregistrare", en: "In the recording" },
  all: { ro: "Arată toate liniile", en: "Show all lines" },
  fewer: { ro: "Arată doar primele linii", en: "Show the first lines" },
  empty: { ro: "Nicio zi în registru.", en: "The registry returned no day." },
  noLines: { ro: "Nicio linie în această zi.", en: "No line on this day." },
  retry: { ro: "Reîncearcă", en: "Retry" },
};

function latestEntry(entries: RegistryEntry[]): RegistryEntry | null {
  let best: RegistryEntry | null = null;
  for (const entry of entries) if (!best || entry.date >= best.date) best = entry;
  return best;
}

function shortHash(hash: string | null | undefined): string | null {
  const trimmed = hash?.trim();
  return trimmed ? trimmed.slice(0, HASH_PREFIX) : null;
}

export function TripRegistry() {
  const { t } = useTranslation();
  const [all, setAll] = useState(false);
  const res = useResource<RegistryDays>("registry", (onPending) => registry(undefined, onPending));
  const data = res.data;
  const day = data ? latestEntry(data.entries) : null;
  const prefix = shortHash(day?.chainHash);
  const shown = all ? day?.lines : day?.lines.slice(0, FIRST);
  const rec = day?.recording;
  const windowText = rec?.firstAt && rec.lastAt ? fmtWindow({ start: rec.firstAt, end: rec.lastAt }) : t("unknown");

  return (
    <section className="trip-registry" aria-labelledby="registry-title">
      <h2 id="registry-title">
        {tr(R.title)}
        {day && data && (
          <>
            {" · "}
            {fmtDate(day.date)}
            {" · "}
            <Figure inline value={day.lines.length} provenance={data.provenance} /> {tr(R.lines)}
            {prefix && (
              <>
                {" · "}
                {tr(R.fingerprint)} <span className="trip-registry-hash" title={day.chainHash ?? undefined}>{prefix}</span>
              </>
            )}
          </>
        )}
      </h2>
      {!data ? (
        <>
          <LoadState loading={res.loading} pending={res.pending} error={res.error} />
          {res.error && (
            <button type="button" className="btn" onClick={() => invalidate("registry")}>
              {tr(R.retry)}
            </button>
          )}
        </>
      ) : !day ? (
        <p className="small muted">{tr(R.empty)}</p>
      ) : (
        <>
          <p className="small">
            {tr(R.recording)}: {windowText}. {tr(R.health)}:{" "}
            <Figure inline value={rec?.healthyShare == null ? null : rec.healthyShare * 100} unit="%" digits={1} provenance={data.provenance} />.
            {" "}
            {tr(R.until)} {rec?.comparedUntil ? fmtDateTime(rec.comparedUntil) : t("unknown")}.{" "}
            {day.final ? tr(R.closed) : tr(R.openDay)} {rec?.l0Complete ? tr(R.compared) : tr(R.partial)}
            {day.feedVersion ? ` GTFS ${day.feedVersion}.` : ""}
          </p>
          {day.lines.length === 0 ? (
            <p className="small muted">{tr(R.noLines)}</p>
          ) : (
            <>
              <table className="table trip-registry-table">
                <thead>
                  <tr>
                    <th scope="col">{tr(R.line)}</th>
                    <th scope="col" className="num">{tr(R.seen)}</th>
                    <th scope="col" className="num">{tr(R.share)}</th>
                    <th scope="col" className="num">{tr(R.km)}, {tr(R.estimate)}</th>
                  </tr>
                </thead>
                <tbody>
                  {shown?.map((line) => (
                    <Fragment key={line.routeId}>
                      <tr>
                        <th scope="row">
                          <span className="line-chip">{line.shortName || line.routeId || t("unknown")}</span>
                          {line.mode && <span className="small muted"> {line.mode}</span>}
                        </th>
                        <td className="num">
                          <Figure inline value={line.tripsSeen} provenance={data.provenance} />
                        </td>
                        <td className="num">
                          <Figure inline value={line.share == null ? null : line.share * 100} unit="%" digits={1} provenance={data.provenance} />
                        </td>
                        <td className="num">
                          <Figure inline value={line.kmEstimated} unit="km" digits={1} provenance={data.provenance} method={line.kmNote} />{" "}
                          <span className="muted">{tr(R.estimate)}</span>
                        </td>
                      </tr>
                      <tr className="trip-registry-detail">
                        <td colSpan={4}>
                          <details>
                            <summary>{tr(R.timetable)}</summary>
                            <p className="small">
                              {tr(R.scheduled)}: <Figure inline value={line.tripsScheduled} provenance={data.provenance} />
                            </p>
                            <p className="small">
                              {tr(R.inRecording)}: <Figure inline value={line.tripsScheduledInRecording} provenance={data.provenance} />
                            </p>
                          </details>
                        </td>
                      </tr>
                    </Fragment>
                  ))}
                </tbody>
              </table>
              {day.lines.length > FIRST && (
                <button type="button" className="linklike small" aria-expanded={all} onClick={() => setAll(!all)}>
                  {tr(all ? R.fewer : R.all)}
                </button>
              )}
            </>
          )}
          {data.provenance.map((p, i) => p.note && (
            <p key={i} className="small muted">{p.note}</p>
          ))}
        </>
      )}
    </section>
  );
}
