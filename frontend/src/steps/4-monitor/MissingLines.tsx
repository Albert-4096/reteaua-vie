// Step 4 for the prepared case case_l23 (O2): the lines with no vehicle in our live recording, one row each.
// We infer from the City Hall's live data; the words stay „fără vehicul în datele live”, never „cursă neefectuată”.
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { api, type Network } from "../../api/client";
import { Figure } from "../../components/Figure";
import { useMapOverlay, type MapStop } from "../../components/MapView";
import { LoadState, Panel } from "../../components/Panel";
import { fmtTime, fmtWindow, tr } from "../../lib/format";
import { navigate, stepHref } from "../../lib/router";
import { useResource } from "../../lib/store";
import type { StepProps } from "../types";
import { fetchMissing, MISSING_CASE, type MissingLines as Missing, type MissingRoute } from "./missing";
import { S } from "./strings";

const M = S.missing;

export function MissingLines({ caseKey }: StepProps) {
  const { t } = useTranslation();
  const res = useResource<Missing>(`missing:${MISSING_CASE}`, fetchMissing);
  const network = useResource<Network>("network", () => api.network());
  const m = res.data;

  const none = useMemo(() => (m?.routes ?? []).filter((r) => r.state === "fara_vehicul"), [m]);
  const mapStops = useMemo(() => {
    const where = new Map((network.data?.stops ?? []).map((s) => [s.id, s.location as [number, number]]));
    return none
      .filter((r) => r.firstMissedTrip && where.has(r.firstMissedTrip.stopId))
      .map((r): MapStop => {
        const f = r.firstMissedTrip!;
        return {
          id: f.stopId,
          name: f.stopName ?? f.stopId,
          location: where.get(f.stopId)!,
          status: "lost",
          label: `${tr(M.line(r.shortName))} · ${tr(M.firstMissed)} ${fmtTime(f.scheduledTime)}`,
        };
      });
  }, [none, network.data]);

  useMapOverlay(
    {
      highlightRouteIds: none.map((r) => r.routeId),
      stops: mapStops,
      stopsText: mapStops.length ? tr(M.mapStops(mapStops.map((s) => s.name).join(", "))) : undefined,
    },
    [none, mapStops],
  );

  if (!m) {
    return (
      <Panel title={tr(M.title)}>
        <LoadState loading={res.loading} error={res.error} />
      </Panel>
    );
  }

  const p = m.provenance;
  const share = m.recording.healthyShare === null ? null : Math.round(m.recording.healthyShare * 100);
  const when = m.case ? `${tr(m.case.label)}, ${fmtTime(m.window.start)}–${fmtTime(m.window.end)}` : fmtWindow(m.window);
  return (
    <Panel
      title={tr(M.title)}
      sentence={tr(M.sentence(when))}
      foot={
        <button type="button" className="btn btn-primary" onClick={() => navigate(stepHref(5, caseKey))}>
          {tr(S.next)}
        </button>
      }
    >
      <div className="figures">
        <Figure value={m.status === "ok" ? none.length : null} label={tr(M.figNone)} provenance={p} />
        <Figure value={m.status === "ok" ? m.routes.length - none.length : null} label={tr(M.figPartial)} provenance={p} />
        <Figure value={share} unit="%" label={tr(M.figHealthy)} provenance={p} />
      </div>

      {m.status !== "ok" ? (
        <p className="st-unsure">{tr(M.incomplete)}</p>
      ) : m.routes.length === 0 ? (
        <p className="muted">{tr(M.empty)}</p>
      ) : (
        <section>
          <h2>{tr(M.list)}</h2>
          <ul className="list small" style={{ marginTop: "var(--sp-2)" }}>
            {m.routes.map((r) => (
              <Row key={r.routeId} r={r} m={m} />
            ))}
          </ul>
        </section>
      )}

      <details>
        <summary>{t("details")}</summary>
        <h3>{tr(M.byMode)}</h3>
        <ul className="list small" style={{ marginTop: "var(--sp-2)" }}>
          {m.byMode.map((b) => (
            <li key={b.mode}>
              {M.mode[b.mode] ? tr(M.mode[b.mode]) : b.mode}: <Figure inline value={b.tripsWithNoVehicle} provenance={p} />{" "}
              {tr(M.of)} <Figure inline value={b.tripsScheduled} provenance={p} />
            </li>
          ))}
        </ul>
        <p className="small" style={{ marginTop: "var(--sp-3)" }}>
          <Figure inline value={m.recording.snapshots} provenance={p} /> {tr(M.recording)}{" "}
          <Figure inline value={m.recording.healthySnapshots} provenance={p} />
        </p>
      </details>
    </Panel>
  );
}

/** One flagged line. „Fără vehicul” stands out; „parțial” is weaker evidence, so it stays muted. */
function Row({ r, m }: { r: MissingRoute; m: Missing }) {
  const { t } = useTranslation();
  const p = m.provenance;
  const strong = r.state === "fara_vehicul";
  const f = r.firstMissedTrip;
  return (
    <li className={strong ? undefined : "muted"}>
      {strong ? <strong>{tr(M.line(r.shortName))}</strong> : tr(M.line(r.shortName))} ·{" "}
      <span className={strong ? "st-lost" : undefined}>{tr(strong ? M.none : M.partial)}</span>
      <br />
      <span>
        {r.since ? tr(M.since(fmtTime(r.since))) : t("unknown")} · <Figure inline value={r.tripsObserved} provenance={p} />{" "}
        {tr(M.seen)} <Figure inline value={r.tripsInService} provenance={p} /> {tr(M.inService)} ·{" "}
        {r.lastSeenAt ? tr(M.lastSeen(fmtTime(r.lastSeenAt))) : tr(M.neverSeen)}
      </span>
      <br />
      <span className="muted">
        {tr(M.firstMissed)}:{" "}
        {f ? (
          <>
            {f.stopName ?? t("unknown")}, {fmtTime(f.scheduledTime)} · <span className="mono">{f.tripId}</span>
          </>
        ) : (
          t("unknown")
        )}
      </span>
    </li>
  );
}
