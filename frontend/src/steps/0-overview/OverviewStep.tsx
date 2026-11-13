// Step 0 Ansamblu: „Cum stă rețeaua azi?” Three figures, the active closures, map layers under „Detalii”.
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type Closure } from "../../api/client";
import { v2, type ClosureSummary, type LayerCollection, type Overview } from "../../api/v2";
import { Figure } from "../../components/Figure";
import { useMapOverlay, type ExtraLayerId } from "../../components/MapView";
import { LoadState, Panel } from "../../components/Panel";
import { fmtDateTime, fmtWindow, tr } from "../../lib/format";
import { navigate, stepHref } from "../../lib/router";
import { useResource } from "../../lib/store";
import { useCases } from "../../lib/useCase";
import type { StepProps } from "../types";
import { S } from "./strings";

type Toggle = "network" | "closures" | "bike" | "parking" | "population";
const TOGGLES: Toggle[] = ["network", "closures", "bike", "parking", "population"];

export function OverviewStep({ caseKey }: StepProps) {
  const { t } = useTranslation();
  const overview = useResource<Overview>("overview", () => v2.overview());
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
                <p className="muted small">{fmtWindow(c.window)}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

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
