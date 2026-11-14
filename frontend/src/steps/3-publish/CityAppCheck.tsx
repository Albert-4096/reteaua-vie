// R27-F: after publish, one row: does the City Hall's own stop timetable still list departures in the closure window?
// A to-do list for the CityApp team, never a verdict on CityApp. Reads GET /api/closures/{id}/timetable-check (R27-B).
// The type is local (only the fields shown here) until schema.d.ts is regenerated.
import { useTranslation } from "react-i18next";
import { apiGet, type I18n, type Provenance } from "../../api/client";
import { fmtDateTime, tr } from "../../lib/format";
import { useResource } from "../../lib/store";
import "./cityAppCheck.css";

type Item = { stopId: string; name: string; shortName: string; directionId: number; departuresListed: number };
type TimetableCheck = {
  state: "ok" | "not_in_force" | "unavailable";
  stopsTotal: number;
  stopsChecked: number;
  items: Item[];
  sentence: I18n;
  provenance: Provenance[];
};

const T = {
  source: { ro: "Sursa", en: "Source" },
  read: { ro: "citit", en: "read" },
  checked: { ro: "stații citite", en: "stops read" },
  of: { ro: "din", en: "of" },
  departures: { ro: "plecări", en: "departures" },
};

export function CityAppCheck({ closureId }: { closureId: string }) {
  const { t } = useTranslation();
  const check = useResource<TimetableCheck>(`timetableCheck:${closureId}`, () =>
    apiGet<TimetableCheck>(`/api/closures/${encodeURIComponent(closureId)}/timetable-check`),
  );
  const c = check.data;
  // Loading or no endpoint on this server: no row (D-011, nothing is shown that the API did not say).
  if (!c) return null;
  if (c.state === "not_in_force") return <p className="small muted tt-check">{tr(c.sentence)}</p>;

  const p = c.provenance[0];
  return (
    <section className="tt-check">
      <p>{tr(c.sentence)}</p>
      {p && (
        <p className="small muted">
          {tr(T.source)}:{" "}
          <a href={`/api/closures/${encodeURIComponent(closureId)}/timetable-check`} target="_blank" rel="noreferrer">
            {p.source.split(" / ")[0]}
          </a>
          {p.fetchedAt ? `, ${tr(T.read)} ${fmtDateTime(p.fetchedAt)}` : ""}
          {` · ${c.stopsChecked} ${tr(T.of)} ${c.stopsTotal} ${tr(T.checked)}`}
        </p>
      )}
      {c.items.length > 0 && (
        <details>
          <summary>{t("details")}</summary>
          <ul className="list small tt-check-list">
            {c.items.map((i) => (
              <li key={`${i.stopId}-${i.shortName}-${i.directionId}`}>
                <span>
                  {i.name} <span className="muted">({i.stopId})</span>
                </span>
                <span className="line-chip">{i.shortName}</span>
                <span className="tt-check-n">
                  {i.departuresListed} {tr(T.departures)}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
