// The step-1 detail tabs under „Detalii”: one tab open at a time, each with 1–2 figures or one short list.
// A tab loads its endpoint only when opened.
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type Network } from "../../../api/client";
import {
  v2,
  type AccessImpact,
  type BikeImpact,
  type Conflict,
  type DetourLoad,
  type ParkingImpact,
  type ReportSummary,
} from "../../../api/v2";
import { Figure } from "../../../components/Figure";
import { LoadState } from "../../../components/Panel";
import { fmtWindow, tr } from "../../../lib/format";
import { useResource, type Resource } from "../../../lib/store";
import { S } from "./strings";

type Tab = keyof typeof S.tab;
const TABS: Tab[] = ["bike", "parking", "access", "detour", "conflicts", "reports"];

export function PlanDetails({ closureId }: { closureId: string }) {
  useTranslation();
  const [tab, setTab] = useState<Tab | null>(null);
  return (
    <section style={{ marginTop: "var(--sp-4)" }}>
      <h3>{tr(S.tabs)}</h3>
      <div className="choice" style={{ marginTop: "var(--sp-2)" }}>
        {TABS.map((k) => (
          <button
            key={k}
            type="button"
            className="btn"
            aria-pressed={tab === k}
            onClick={() => setTab(tab === k ? null : k)}
          >
            {tr(S.tab[k])}
          </button>
        ))}
      </div>
      {tab && (
        <div style={{ marginTop: "var(--sp-3)" }}>
          {tab === "bike" && <Bike id={closureId} />}
          {tab === "parking" && <Parking id={closureId} />}
          {tab === "access" && <Access id={closureId} />}
          {tab === "detour" && <Detour id={closureId} />}
          {tab === "conflicts" && <Conflicts id={closureId} />}
          {tab === "reports" && <Reports id={closureId} />}
        </div>
      )}
    </section>
  );
}

function Loading<T>({ r }: { r: Resource<T> }) {
  return <LoadState loading={r.loading} pending={r.pending} error={r.error} />;
}

function Bike({ id }: { id: string }) {
  const r = useResource<BikeImpact>(`bike:${id}`, () => v2.bike(id));
  if (!r.data) return <Loading r={r} />;
  const meters = r.data.lanesAffected.reduce((s, l) => s + l.lengthMeters, 0);
  return (
    <div className="figures" style={{ gridTemplateColumns: "1fr 1fr" }}>
      <Figure value={Math.round(meters)} unit="m" label={tr(S.bikeLanes)} provenance={r.data.provenance} />
      <Figure value={r.data.parkingAffected.length} label={tr(S.bikeParking)} provenance={r.data.provenance} />
    </div>
  );
}

function Parking({ id }: { id: string }) {
  const r = useResource<ParkingImpact>(`parking:${id}`, () => v2.parking(id));
  if (!r.data) return <Loading r={r} />;
  const all = [...r.data.streetsAffected, ...r.data.lotsAffected];
  const names = [...new Set(all.map((s) => s.name))];
  return (
    <>
      <Figure value={names.length} label={tr(S.parkingStreets)} provenance={r.data.provenance} />
      <ul className="list small" style={{ marginTop: "var(--sp-2)" }}>
        {names.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
    </>
  );
}

function Access({ id }: { id: string }) {
  const r = useResource<AccessImpact>(`access:${id}:hospital:30`, (onPending) => v2.access(id, onPending));
  if (r.error) return <p className="error-msg">{tr(S.accessError)}</p>;
  if (!r.data) return <Loading r={r} />;
  const a = r.data;
  const zones = a.byZone.filter((z) => (z.residentsLosing ?? 0) > 0).sort((x, y) => (y.residentsLosing ?? 0) - (x.residentsLosing ?? 0));
  return (
    <>
      <Figure value={a.totals.residentsLosing} label={tr(S.accessFig)} provenance={a.provenance} method={tr(a.method)} />
      <p className="small muted" style={{ marginTop: "var(--sp-1)" }}>
        {tr(S.estimate)}
      </p>
      {zones.length === 0 ? (
        <p className="small" style={{ marginTop: "var(--sp-2)" }}>
          {tr(S.accessNone)}
        </p>
      ) : (
        <table className="table" style={{ marginTop: "var(--sp-2)" }}>
          <caption className="visually-hidden">{tr(S.accessZones)}</caption>
          <tbody>
            {zones.map((z) => (
              <tr key={z.slug}>
                <td>{z.name}</td>
                <td className="num">
                  <Figure inline value={z.residentsLosing} provenance={a.provenance} method={tr(a.method)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function Detour({ id }: { id: string }) {
  const r = useResource<DetourLoad>(`detour:${id}`, (onPending) => v2.detourLoad(id, onPending));
  const net = useResource<Network>("network", () => api.network());
  if (!r.data) return <Loading r={r} />;
  const d = r.data;
  const short = (rid: string) => net.data?.routes.find((x) => x.id === rid)?.shortName ?? rid;
  const lines = [...d.routesSlowedRisk].map(short).sort((x, y) => x.localeCompare(y, "ro", { numeric: true }));
  const streets = [...new Set(d.edges.map((e) => e.name).filter((n): n is string => !!n))];
  return (
    <>
      <p className="small muted">{tr(d.label)}</p>
      <h3 style={{ marginTop: "var(--sp-2)" }}>{tr(S.detourLines)}</h3>
      {lines.length === 0 ? (
        <p className="small">{tr(S.detourNone)}</p>
      ) : (
        <p className="mono" style={{ marginTop: "var(--sp-1)" }}>
          {lines.join(", ")}
        </p>
      )}
      {streets.length > 0 && (
        <p className="small" style={{ marginTop: "var(--sp-2)" }}>
          <span className="muted">{tr(S.detourStreets)}: </span>
          {streets.join(", ")}
        </p>
      )}
    </>
  );
}

function Conflicts({ id }: { id: string }) {
  const r = useResource<Conflict[]>(`conflicts:${id}`, () => v2.conflicts(id));
  if (!r.data) return <Loading r={r} />;
  // One row per other closure; its kinds of overlap in words.
  const byOther = new Map<string, { c: Conflict; kinds: string[] }>();
  for (const c of r.data) {
    const cur = byOther.get(c.otherClosureId) ?? { c, kinds: [] };
    cur.kinds.push(tr(S.kind[c.kind] ?? { ro: c.kind }));
    byOther.set(c.otherClosureId, cur);
  }
  if (byOther.size === 0) return <p className="small">{tr(S.conflictsNone)}</p>;
  return (
    <ul className="list small">
      {[...byOther.values()].map(({ c, kinds }) => (
        <li key={c.otherClosureId}>
          {tr(c.otherTitle)}
          <br />
          <span className="muted">
            {kinds.join(", ")} · {fmtWindow(c.overlap)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Reports({ id }: { id: string }) {
  const r = useResource<ReportSummary>(`reports:${id}`, () => v2.reports(id));
  if (!r.data) return <Loading r={r} />;
  const s = r.data;
  return (
    <>
      <Figure value={s.total} label={tr(S.reportsFig(Math.round(s.radiusMeters)))} provenance={s.provenance} />
      {s.total === null && (
        <p className="small muted" style={{ marginTop: "var(--sp-1)" }}>
          {tr(S.reportsUncovered(fmtWindow({ start: s.from, end: s.to })))}
          {s.coveredFrom && s.coveredTo && ` ${tr(S.reportsCovered(fmtWindow({ start: s.coveredFrom, end: s.coveredTo })))}`}
        </p>
      )}
      {s.total === 0 && <p className="small">{tr(S.reportsNone)}</p>}
      {s.byCategory.length > 0 && (
        <table className="table" style={{ marginTop: "var(--sp-2)" }}>
          <tbody>
            {s.byCategory.map((c) => (
              <tr key={c.category}>
                <td>{c.category}</td>
                <td className="num">
                  <Figure inline value={c.count} provenance={s.provenance} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
