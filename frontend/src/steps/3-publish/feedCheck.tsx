// R21-F: after publish, one row: does the published alert still hold on the next SMTT timetable version?
// Reads GET /api/closures/{id}/feed-check (R21-B, CONTRACT v2.15); the backend picks the next version by default.
// The type is local (only the fields shown here) until schema.d.ts is regenerated.
import { useTranslation } from "react-i18next";
import { api, apiGet, type I18n, type Network, type Provenance } from "../../api/client";
import { Figure } from "../../components/Figure";
import { fmtDateTime, tr } from "../../lib/format";
import { useResource } from "../../lib/store";
import "./feedCheck.css";

type RowStatus = "ok" | "stop_missing" | "route_missing" | "not_served" | "now_served" | "renamed" | "moved";
type Row = { stopId: string; name: string; routeId: string; directionId: number; status: RowStatus };
type Version = { version: string; trips: number | null };
type FeedCheck = {
  base: Version;
  target: Version;
  verdict: "valid" | "republish" | "check" | "not_applicable";
  rows: Row[];
  summary: I18n;
  draftNotice: I18n | null;
  diff: { stopsRemoved: { stopId: string; name: string }[]; tripsChanged: number };
  provenance: Provenance[];
};

const VERDICT_CLASS = { valid: "st-ok", republish: "st-lost", check: "st-unsure" } as const;
// Local until 3-publish/strings.ts is free (same as CityAppCheck); the summary itself comes from the API.
const F = {
  label: { ro: "Orarul următor", en: "Next timetable" },
  allOk: {
    ro: "Rânduri ale anunțului neschimbate (linie, stație, sens):",
    en: "Unchanged notice rows (line, stop, direction):",
  },
  status: {
    ok: { ro: "la fel", en: "same" },
    stop_missing: { ro: "stația nu mai există", en: "stop removed" },
    route_missing: { ro: "linia nu mai există", en: "line removed" },
    not_served: { ro: "nu mai oprește aici", en: "no longer stops here" },
    now_served: { ro: "oprește din nou aici", en: "stops here again" },
    renamed: { ro: "stație redenumită", en: "stop renamed" },
    moved: { ro: "stație mutată", en: "stop moved" },
  },
  draft: { ro: "Anunț de republicat (ciornă)", en: "Notice to republish (draft)" },
  diff: { ro: "Ce se schimbă în orar", en: "What changes in the timetable" },
  stopsRemoved: { ro: "Stații scoase", en: "Stops removed" },
  tripsChanged: { ro: "Curse cu stații schimbate", en: "Trips with changed stops" },
  of: { ro: "din", en: "of" },
  source: { ro: "Sursa", en: "Source" },
};

export function FeedCheckRow({ closureId }: { closureId: string }) {
  const { t } = useTranslation();
  const url = `/api/closures/${encodeURIComponent(closureId)}/feed-check`;
  const check = useResource<FeedCheck>(`feedCheck:${closureId}`, () => apiGet<FeedCheck>(url));
  const net = useResource<Network>("network", () => api.network());
  const c = check.data;
  // Loading, no next version or no alert rows (404/409): no row; nothing is shown that the API did not say (D-011).
  if (!c) return null;
  if (c.verdict === "not_applicable") return <p className="small muted feed-check">{tr(c.summary)}</p>;

  const short = (rid: string) => net.data?.routes.find((r) => r.id === rid)?.shortName ?? rid;
  const changed = c.rows.filter((r) => r.status !== "ok");
  const removed = c.diff.stopsRemoved;
  const prov = c.provenance;

  return (
    <section className="feed-check" aria-label={tr(F.label)}>
      <p className={VERDICT_CLASS[c.verdict]}>{tr(c.summary)}</p>
      <details>
        <summary>{t("details")}</summary>
        {changed.length === 0 ? (
          <p className="small">{tr(F.allOk)} <Figure inline value={c.rows.length} provenance={prov} /></p>
        ) : (
          <ul className="list small feed-check-list">
            {changed.map((r) => (
              <li key={`${r.stopId}-${r.routeId}-${r.directionId}`}>
                <span>
                  {r.name} <span className="muted">({r.stopId})</span>
                </span>
                <span className="line-chip">{short(r.routeId)}</span>
                <span className={r.status === "now_served" ? "st-unsure" : "st-lost"}>{tr(F.status[r.status])}</span>
              </li>
            ))}
          </ul>
        )}
        {c.draftNotice && (
          <>
            <h3 className="feed-check-h">{tr(F.draft)}</h3>
            <p className="notice-text">{tr(c.draftNotice)}</p>
          </>
        )}
        <h3 className="feed-check-h">
          {tr(F.diff)} {c.base.version} → {c.target.version}
        </h3>
        <p className="small">
          {tr(F.stopsRemoved)}: <Figure inline value={removed.length} provenance={prov} />
          {removed.length > 0 && <span className="muted"> ({removed.map((s) => `${s.name}, ${s.stopId}`).join("; ")})</span>}
          <br />
          {tr(F.tripsChanged)}: <Figure inline value={c.diff.tripsChanged} provenance={prov} />
          {c.target.trips !== null && (
            <span className="muted">
              {" "}
              {tr(F.of)} <Figure inline value={c.target.trips} provenance={prov} />
            </span>
          )}
        </p>
        <p className="small muted">
          {tr(F.source)}:{" "}
          <a href={url} target="_blank" rel="noreferrer">
            {prov[0]?.source.split(" (")[0] ?? "GTFS"}
          </a>
          {prov.map((p) => (p.version ? ` ${p.version}${p.fetchedAt ? ` (${fmtDateTime(p.fetchedAt)})` : ""}` : "")).join(",")}
        </p>
      </details>
    </section>
  );
}
