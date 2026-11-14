// Step 4 Urmărești: „Se respectă devierea?” The recorded passes at each suspended stop: skipped, served, unknown.
// The prepared case case_l23 (`?case=l23`) shows the lines with no vehicle instead (MissingLines.tsx).
// The only closure with a vehicle recording is the Mocioni diversion (SPEC 5.3), so the prepared case
// opens it unless the URL names a closure directly (`?closure=`).
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { api, apiGet, type Closure, type Network, type Provenance } from "../../api/client";
import { DEVIATIONS_KEY, deviationTracks, fetchDeviations, type Deviations as DeviationReport } from "../../api/deviations";
import { v2, type LayerCollection, type LiveCheck } from "../../api/v2";
import { Figure } from "../../components/Figure";
import { DetourCost } from "../../components/DetourCost";
import { useMapOverlay, type ExtraLayerId, type MapStop } from "../../components/MapView";
import { LoadState, Panel } from "../../components/Panel";
import { fmtDateTime, tr } from "../../lib/format";
import { navigate, stepHref } from "../../lib/router";
import { useResource } from "../../lib/store";
import { useCases } from "../../lib/useCase";
import type { StepProps } from "../types";
import { Deviations } from "./Deviations";
import { isMissingCase } from "./missing";
import { MissingLines } from "./MissingLines";
import { S } from "./strings";

const LIVE_CASE = "case_mocioni";

// CONTRACT v2.11 ScanCounts (not in the generated schema yet).
type ScanCounts = {
  closureId: string;
  total: number;
  bucket: "hour";
  stops: { stopId: string; count: number; firstBucket: string; lastBucket: string }[];
  provenance: Provenance[];
};

type StopRow = { stopId: string; name: string; skipped: number; served: number; unknown: number };

/** `?case=l23` (O2) lists the lines with no vehicle; any other case checks a diversion. */
export function MonitorStep(props: StepProps) {
  return isMissingCase(props.caseKey) ? <MissingLines {...props} /> : <DiversionCheck {...props} />;
}

function DiversionCheck({ caseKey, closureId }: StepProps) {
  const { t, i18n } = useTranslation();
  const cases = useCases();
  const id = !caseKey && closureId ? closureId : (cases.data?.find((c) => c.id === LIVE_CASE)?.closureId ?? null);
  const closure = useResource<Closure>(id ? `closure:${id}` : null, () => api.closure(id!));
  const live = useResource<LiveCheck>(id ? `live:${id}` : null, () => v2.live(id!));
  const network = useResource<Network>("network", () => api.network());
  const vehicles = useResource<LayerCollection>("vehicles", () => v2.vehicles());
  const scans = useResource<ScanCounts>(id ? `scans:${id}` : null, () =>
    apiGet<ScanCounts>(`/api/closures/${encodeURIComponent(id!)}/scans`),
  );
  const deviations = useResource<DeviationReport>(DEVIATIONS_KEY, fetchDeviations);

  const c = closure.data;
  const l = live.data;
  const rows = useMemo(() => stopRows(l), [l]);
  const routeIds = c?.routeIds ?? [];
  const ownVehicles = useMemo(() => {
    if (!vehicles.data) return null;
    const fs = vehicles.data.features.filter((f) => routeIds.includes(String(f.properties.routeId)));
    return { type: "FeatureCollection", features: fs } as unknown as GeoJSON.FeatureCollection;
  }, [vehicles.data, routeIds.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  const mapStops = useMemo(() => {
    const where = new Map((network.data?.stops ?? []).map((s) => [s.id, s.location as [number, number]]));
    return rows
      .filter((r) => where.has(r.stopId))
      .map((r): MapStop => {
        const st = rowState(r);
        return {
          id: r.stopId,
          name: r.name,
          location: where.get(r.stopId)!,
          status: st === "skipped" ? "lost" : st === "served" ? "unsure" : "served",
          label: summaryWords(r),
        };
      });
  }, [rows, network.data]);

  const deviationLines = useMemo(() => deviationTracks(deviations.data), [deviations.data]);
  const layers = useMemo(() => {
    const next: { id: ExtraLayerId; data: GeoJSON.FeatureCollection; label?: string }[] = [];
    if (ownVehicles) next.push({ id: "vehicles", data: ownVehicles });
    if (deviationLines.features.length > 0) {
      next.push({
        id: "deviations",
        data: deviationLines,
        label: tr({
          ro: `trasee deviate înregistrate: ${deviationLines.features.length}`,
          en: `recorded off-route tracks: ${deviationLines.features.length}`,
        }),
      });
    }
    return next;
  }, [ownVehicles, deviationLines, i18n.language]);

  useMapOverlay(
    {
      closure: (c?.geometry as GeoJSON.Geometry | null) ?? null,
      highlightRouteIds: routeIds,
      stops: mapStops,
      // The colours mean skipped / served / unknown here, so the map's text equivalent says so.
      stopsText: tr(
        S.mapStops({
          skipped: mapStops.filter((s) => s.status === "lost").length,
          served: mapStops.filter((s) => s.status === "unsure").length,
          unknown: mapStops.filter((s) => s.status === "served").length,
        }),
      ),
      layers,
      fitKey: c && mapStops.length ? `monitor:${id}` : undefined,
    },
    [c, mapStops, layers, id],
  );

  if (!c || !l) {
    return (
      <Panel title={tr(S.title)}>
        <LoadState
          loading={cases.loading || closure.loading || live.loading}
          error={cases.error ?? closure.error ?? live.error}
        />
      </Panel>
    );
  }

  const stopName = new Map((network.data?.stops ?? []).map((s) => [s.id, s.name]));
  const recorded = l.source !== null && l.recordedFrom && l.recordedTo;
  const vAt = vehicles.data?.provenance[0]?.fetchedAt;
  return (
    <Panel
      title={tr(S.title)}
      sentence={
        <>
          {recorded
            ? tr(S.sentence(tr(c.title), fmtDateTime(l.from), fmtDateTime(l.to)))
            : `${tr(c.title)}. ${tr(S.noRecording)}`}
          {c.reconstructed && (
            <span className="small muted" title={c.reconstructedNote ? tr(c.reconstructedNote) : undefined}>
              {" "}· reconstituit
            </span>
          )}
        </>
      }
      foot={
        <button type="button" className="btn btn-primary" onClick={() => navigate(stepHref(5, caseKey))}>
          {tr(S.next)}
        </button>
      }
    >
      <div className="figures">
        <Figure value={l.summary.stopsSkipped} label={tr(S.figSkipped)} provenance={l.provenance} method={l.method ? tr(l.method) : null} />
        <Figure value={l.summary.stopsServedAnyway} label={tr(S.figServed)} provenance={l.provenance} method={l.method ? tr(l.method) : null} />
        <Figure value={l.summary.stopsUnknown} label={tr(S.figUnknown)} provenance={l.provenance} method={l.method ? tr(l.method) : null} />
      </div>

      {rows.length > 0 && (
        <section>
          <h2>{tr(S.list)}</h2>
          <ul className="list small" style={{ marginTop: "var(--sp-2)" }}>
            {rows.map((r) => (
              <li key={r.stopId}>
                {r.name}
                <br />
                <span className="muted">
                  {tr(S.skipped)} <Figure inline value={r.skipped} provenance={l.provenance} /> ·{" "}
                </span>
                {/* Served despite the suspension: the notice or our list may be wrong, so it stands out. */}
                <span className={r.served > 0 ? "st-unsure" : "muted"}>
                  {tr(S.served)} <Figure inline value={r.served} provenance={l.provenance} />
                </span>
                <span className="muted">
                  {" "}
                  · {tr(S.unknown)} <Figure inline value={r.unknown} provenance={l.provenance} />
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <Deviations result={deviations} />

      {id && <DetourCost closureId={id} detailed />}

      {!scans.loading && (
        <p className="small">
          {tr(S.scans)}{" "}
          <Figure inline value={scans.error ? null : scans.data?.total} provenance={scans.data?.provenance} method={tr(S.scansHint)} />
        </p>
      )}

      <details>
        <summary>{t("details")}</summary>
        {scans.data && scans.data.stops.length > 0 && (
          <p className="small">
            {tr(S.scansByStop)}:{" "}
            {scans.data.stops.map((s, i) => (
              <span key={s.stopId}>
                {i > 0 && " · "}
                {stopName.get(s.stopId) ?? s.stopId} <Figure inline value={s.count} provenance={scans.data?.provenance} />
              </span>
            ))}
          </p>
        )}
        <p className="small">
          <Figure inline value={l.summary.vehiclesSeen} provenance={l.provenance} /> {tr(S.seen)}
        </p>
        {vAt && ownVehicles && (
          <p className="small" style={{ marginTop: "var(--sp-2)" }}>
            <Figure inline value={ownVehicles.features.length} provenance={vehicles.data?.provenance} />{" "}
            {tr(S.vehicles(fmtDateTime(vAt)))}
          </p>
        )}
        {l.method && (
          <>
            <h3 style={{ marginTop: "var(--sp-3)" }}>{tr(S.method)}</h3>
            <p className="small">{tr(l.method)}</p>
          </>
        )}
      </details>
    </Panel>
  );
}

/** One row per suspended stop id, summed over the lines and directions that pass it. */
function stopRows(l: LiveCheck | undefined): StopRow[] {
  const by = new Map<string, StopRow>();
  for (const r of l?.byStop ?? []) {
    const cur = by.get(r.stopId) ?? { stopId: r.stopId, name: r.name ?? r.stopId, skipped: 0, served: 0, unknown: 0 };
    cur.skipped += r.skipped;
    cur.served += r.served;
    cur.unknown += r.unknown;
    by.set(r.stopId, cur);
  }
  return [...by.values()].sort((a, b) => b.served - a.served || b.skipped - a.skipped);
}

/** Served at least once = the notice or our list may be wrong; else skipped if any pass was seen. */
function rowState(r: StopRow): "skipped" | "served" | "unknown" {
  if (r.served > 0) return "served";
  if (r.skipped > 0) return "skipped";
  return "unknown";
}

function summaryWords(r: StopRow): string {
  return `${tr(S.skipped)} ${r.skipped}, ${tr(S.served)} ${r.served}, ${tr(S.unknown)} ${r.unknown}`;
}
