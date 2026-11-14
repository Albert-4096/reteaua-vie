// Step 0 Ansamblu: „Cum stă rețeaua azi?” Three figures, the active closures, map layers under „Detalii”.
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type Closure } from "../../api/client";
import { v2, type ClosureSummary, type LayerCollection } from "../../api/v2";
import { Figure } from "../../components/Figure";
import { useMapOverlay, type ExtraLayerId } from "../../components/MapView";
import { LoadState, Panel } from "../../components/Panel";
import { fmtDateTime, fmtTime, fmtWindow, tr } from "../../lib/format";
import { navigate, stepHref } from "../../lib/router";
import { useResource } from "../../lib/store";
import { useCases } from "../../lib/useCase";
import {
  briefProvenance,
  MISSING_CASE_KEY,
  type MissingBrief,
  type OverviewWithMissing,
} from "../4-monitor/missing";
import type { StepProps } from "../types";
import { S } from "./strings";

type Toggle = "network" | "closures" | "bike" | "parking" | "population";
const TOGGLES: Toggle[] = ["network", "closures", "bike", "parking", "population"];

export function OverviewStep({ caseKey }: StepProps) {
  const { t } = useTranslation();
  const overview = useResource<OverviewWithMissing>("overview", () => v2.overview());
  const cases = useCases();
  const [on, setOn] = useState<Record<Toggle, boolean>>({
    network: true,
    closures: true,
    bike: false,
    parking: false,
    population: false,
  });

  const active = overview.data?.activeClosures ?? [];
  const ids = active.map((c) => c.id).join(",");
  const geoms = useResource<Closure[]>(ids ? `overview-closures:${ids}` : null, () =>
    Promise.all(active.map((c) => api.closure(c.id))),
  );
  const bike = useResource<LayerCollection>(on.bike ? "layer:bike" : null, () => v2.layer("bike"));
  const parking = useResource<LayerCollection>(on.parking ? "layer:parking" : null, () => v2.layer("parking"));
  const population = useResource<LayerCollection>(on.population ? "layer:population" : null, () =>
    v2.layer("population"),
  );

  const closureGeom = useMemo(() => mergeLines((geoms.data ?? []).map((c) => c.geometry)), [geoms.data]);
  const routeIds = useMemo(() => [...new Set(active.flatMap((c) => c.routeIds))], [ids]); // eslint-disable-line react-hooks/exhaustive-deps
  const layers: { id: ExtraLayerId; data: GeoJSON.FeatureCollection }[] = [];
  for (const [k, r] of [["bike", bike], ["parking", parking], ["population", population]] as const)
    if (on[k] && r.data) layers.push({ id: k, data: r.data as unknown as GeoJSON.FeatureCollection });

  useMapOverlay(
    {
      closure: on.closures ? closureGeom : null,
      highlightRouteIds: on.closures ? routeIds : [],
      layers,
      hideNetwork: !on.network,
      fitKey: closureGeom ? `overview:${ids}` : undefined,
    },
    [closureGeom, routeIds, on, bike.data, parking.data, population.data, ids],
  );

  const o = overview.data;
  if (!o) {
    return (
      <Panel title={tr(S.title)}>
        <LoadState loading={overview.loading} error={overview.error} />
      </Panel>
    );
  }

  const dossier = (c: ClosureSummary) => {
    const hit = cases.data?.find((k) => k.closureId === c.id);
    return hit ? stepHref(1, hit.id.replace(/^case_/, "")) : `/step/1?closure=${encodeURIComponent(c.id)}`;
  };
  const layerState = (k: Toggle) => (k === "bike" ? bike : k === "parking" ? parking : k === "population" ? population : null);

  return (
    <Panel
      title={tr(S.title)}
      sentence={tr(S.sentence(fmtDateTime(o.at)))}
      foot={
        <button type="button" className="btn btn-primary" onClick={() => navigate(stepHref(1, caseKey))}>
          {tr(S.plan)}
        </button>
      }
    >
      <div className="figures">
        <Figure value={o.activeClosures.length} label={tr(S.figClosures)} provenance={o.provenance} />
        <Figure value={o.ghostDeparturesToday} label={tr(S.figGhost)} provenance={o.provenance} />
        <Figure
          value={o.vehiclesLive}
          label={tr(S.figVehicles(o.vehiclesAt ? fmtDateTime(o.vehiclesAt) : t("unknown")))}
          provenance={o.provenance}
        />
      </div>

      <section>
        <h2>{tr(S.list)}</h2>
        {o.activeClosures.length === 0 ? (
          <p className="muted">{tr(S.none)}</p>
        ) : (
          <ul className="list" style={{ marginTop: "var(--sp-2)" }}>
            {o.activeClosures.map((c) => (
              <li key={c.id}>
                <a
                  href={dossier(c)}
                  onClick={(e) => {
                    e.preventDefault();
                    navigate(dossier(c));
                  }}
                >
                  {tr(c.title)}
                </a>
                {/* published by make precompute from the STPT notice, not live (RoseLark, D-010 rule) */}
                {c.reconstructed && (
                  <span className="small muted" title={c.reconstructedNote ? tr(c.reconstructedNote) : undefined}>
                    {" "}· reconstituit
                  </span>
                )}
                <p className="muted small">{fmtWindow(c.window)}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      {o.missingLines !== undefined && <MissingSection o={o} />}

      <details>
        <summary>{t("details")}</summary>
        <fieldset style={{ border: 0, margin: 0, padding: 0, display: "grid", gap: "var(--sp-1)" }}>
          <legend className="small muted" style={{ padding: 0, marginBottom: "var(--sp-1)" }}>
            {tr(S.layers)}
          </legend>
          {TOGGLES.map((k) => {
            const st = layerState(k);
            return (
              <label key={k}>
                <input type="checkbox" checked={on[k]} onChange={(e) => setOn({ ...on, [k]: e.target.checked })} />{" "}
                {tr(S.layer[k])}
                {st && on[k] && (st.loading || st.error) && (
                  <span className="small muted"> · {st.error ? st.error.code : "…"}</span>
                )}
              </label>
            );
          })}
        </fieldset>
        {o.compliance && (
          <p className="small" style={{ marginTop: "var(--sp-3)" }}>
            {tr(S.compliance)}: <Figure inline value={o.compliance.covered} provenance={o.provenance} /> {tr(S.covered)},{" "}
            <Figure inline value={o.compliance.partial} provenance={o.provenance} /> {tr(S.partial)},{" "}
            <Figure inline value={o.compliance.missing} provenance={o.provenance} /> {tr(S.missing)}.
          </p>
        )}
        {o.upcomingClosures.length > 0 && (
          <>
            <h3 style={{ marginTop: "var(--sp-3)" }}>{tr(S.upcoming)}</h3>
            <ul className="list small">
              {o.upcomingClosures.map((c) => (
                <li key={c.id}>
                  {tr(c.title)} <span className="muted">· {fmtWindow(c.window)}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </details>
    </Panel>
  );
}

/** O2: the prepared case (14 Nov, opens in step 4) and the last 60 minutes; only the lines with no vehicle are rows. */
function MissingSection({ o }: { o: OverviewWithMissing }) {
  const { t } = useTranslation();
  const M = S.noVehicle;
  const prepared = o.missingLines?.prepared ?? null;
  const live = o.missingLines?.live ?? null;
  const parts: { key: string; b: MissingBrief | null; when: string; href: string | null }[] = [];
  if (prepared) {
    const when = `${prepared.case ? tr(prepared.case.label) : ""}, ${fmtTime(prepared.window.start)}–${fmtTime(prepared.window.end)}`;
    parts.push({ key: "prepared", b: prepared, when, href: stepHref(4, MISSING_CASE_KEY) });
  }
  parts.push({ key: "live", b: live, when: tr(M.now), href: null });
  return (
    <section>
      <h2>{tr(M.title)}</h2>
      <p className="small muted">{tr(M.label)}</p>
      <ul className="list" style={{ marginTop: "var(--sp-2)" }}>
        {parts.map(({ key, b, when, href }) => {
          const p = b ? briefProvenance(o.provenance, b) : [];
          const ok = b?.status === "ok";
          return (
            <li key={key}>
              <p className="small muted">
                {tr(M.brief(when))} <Figure inline value={ok ? b.count : null} provenance={p} />{" "}
                {ok && (
                  <>
                    {tr(M.partial)} <Figure inline value={b.partialCount} provenance={p} />
                  </>
                )}
                {b && !ok && <> · {tr(M.incomplete)}</>}
              </p>
              {ok &&
                b.rows
                  .filter((r) => r.state === "fara_vehicul")
                  .map((r) => (
                    <p key={r.routeId}>
                      {href ? (
                        <a
                          href={href}
                          onClick={(e) => {
                            e.preventDefault();
                            navigate(href);
                          }}
                        >
                          {tr(M.line(r.shortName))}
                        </a>
                      ) : (
                        tr(M.line(r.shortName))
                      )}
                      {tr(M.row(r.since ? fmtTime(r.since) : t("unknown")))}
                      <Figure inline value={r.tripsInService} provenance={p} /> {tr(M.trips)}
                    </p>
                  ))}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** All closed sections in one MultiLineString, so the existing closure layer draws every active closure. */
function mergeLines(gs: (unknown | null | undefined)[]): GeoJSON.MultiLineString | null {
  const lines: GeoJSON.Position[][] = [];
  for (const g of gs as (GeoJSON.Geometry | null | undefined)[]) {
    if (!g) continue;
    if (g.type === "LineString") lines.push(g.coordinates);
    else if (g.type === "MultiLineString") lines.push(...g.coordinates);
  }
  return lines.length ? { type: "MultiLineString", coordinates: lines } : null;
}
