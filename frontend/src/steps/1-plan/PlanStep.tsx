// Step 1 Planifici: what closes, which lines lose which stops, one question per unsure group, three figures.
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type AffectedStop, type Analysis, type Closure, type Impact, type Network } from "../../api/client";
import { CasePicker } from "../../components/CasePicker";
import { Figure } from "../../components/Figure";
import { LineSchema } from "../../components/LineSchema";
import { useMapOverlay, type MapStop } from "../../components/MapView";
import { LoadState, Panel } from "../../components/Panel";
import { decisionGroups, groupDecisions, groupState, undecidedCount, type Group } from "../../lib/decisions";
import { fmtWindow, tr } from "../../lib/format";
import { lineSchema, rowStatus } from "../../lib/geo";
import { navigate, stepHref } from "../../lib/router";
import { invalidate, setData, useResource } from "../../lib/store";
import type { StepProps } from "../types";
import { PlanDetails } from "./details/PlanDetails";

export function PlanStep(props: StepProps) {
  if (!props.closureId) return <CasePicker step={1} />;
  return <Plan {...props} closureId={props.closureId} />;
}

function Plan({ closureId, caseKey }: StepProps & { closureId: string }) {
  const { t } = useTranslation();
  const closure = useResource<Closure>(`closure:${closureId}`, () => api.closure(closureId));
  const analysis = useResource<Analysis>(`analysis:${closureId}`, () => api.analysis(closureId));
  const impact = useResource<Impact>(`impact:${closureId}`, () => api.impact(closureId));
  const network = useResource<Network>("network", () => api.network());
  const [open, setOpen] = useState<string[] | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const a = analysis.data;
  const c = closure.data;
  const groups = useMemo(() => (a ? decisionGroups(a) : []), [a]);
  const routes = useMemo(
    () => [...(a?.routes ?? [])].sort((x, y) => x.shortName.localeCompare(y.shortName, "ro", { numeric: true })),
    [a],
  );
  const expanded = open ?? routes.filter((r) => groups.some((g) => g.routeId === r.routeId && groupState(g) === "open")).map((r) => r.routeId);

  const mapStops = useMemo(() => (a ? stopsForMap(a.stops, (k) => t(k)) : []), [a, t]);
  useMapOverlay(
    {
      closure: (c?.geometry as GeoJSON.Geometry | null) ?? null,
      tempRoutes: (c?.temporaryRoutes ?? []).map((r) => r.geometry as unknown as GeoJSON.Geometry).filter(Boolean),
      highlightRouteIds: expanded.length > 0 ? expanded : routes.map((r) => r.routeId),
      stops: mapStops,
      note: c?.locationNote ? tr(c.locationNote) : undefined,
      fitKey: c && a ? closureId : undefined,
    },
    [c, a, mapStops, expanded.join(","), closureId],
  );

  const err = closure.error ?? analysis.error;
  if (err || !c || !a) {
    return (
      <Panel title={c ? tr(c.title) : t("steps.1")}>
        <LoadState loading error={err} />
      </Panel>
    );
  }

  const left = undecidedCount(a);

  async function choose(g: Group, lost: boolean) {
    setSaving(g.id);
    setSaveError(null);
    try {
      const next = await api.decide(closureId, groupDecisions(g, lost));
      setData(`analysis:${closureId}`, next);
      invalidate(`impact:${closureId}`, `notice:${closureId}`, `closure:${closureId}`);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(null);
    }
  }

  const tot = impact.data?.totals;
  return (
    <Panel
      title={tr(c.title)}
      sentence={t(left > 0 ? "plan.sentence" : "plan.sentenceDone", { window: fmtWindow(c.window) })}
      foot={
        <>
          <button
            type="button"
            className="btn btn-primary"
            disabled={left > 0}
            onClick={() => navigate(stepHref(3, caseKey))}
          >
            {t("plan.confirm")}
          </button>
          {left > 0 && <p className="hint">{t("plan.confirmHint", { count: left })}</p>}
        </>
      }
    >
      <div className="figures">
        {impact.data ? (
          <>
            <Figure value={tot?.stopsSuspended} label={t("plan.figStops")} provenance={impact.data.provenance} method={tr(impact.data.method)} />
            <Figure value={tot?.departuresLost} label={t("plan.figDepartures")} provenance={impact.data.provenance} method={tr(impact.data.method)} />
            <Figure value={tot?.residentsLosingStop} label={t("plan.figResidents")} provenance={impact.data.provenance} method={tr(impact.data.method)} />
          </>
        ) : (
          <LoadState {...impact} loading />
        )}
      </div>

      <section aria-labelledby="lines-h">
        <h2 id="lines-h" className="small muted" style={{ fontWeight: 600, marginBottom: "var(--sp-2)" }}>
          {t("plan.lines")}
        </h2>
        <ul className="list">
          {routes.map((r) => {
            const rows = a.stops.filter((s) => s.routeId === r.routeId);
            const isOpen = expanded.includes(r.routeId);
            const action = c.routeActions?.find((x) => x.routeId === r.routeId)?.action;
            const lostNames = new Set(rows.filter((s) => rowStatus(s) === "lost").map((s) => s.name)).size;
            const unsure = rows.filter((s) => rowStatus(s) === "unsure").length;
            const myGroups = groups.filter((g) => g.routeId === r.routeId);
            return (
              <li key={r.routeId}>
                <button
                  type="button"
                  className="row-button"
                  aria-expanded={isOpen}
                  onClick={() => setOpen(isOpen ? expanded.filter((x) => x !== r.routeId) : [...expanded, r.routeId])}
                >
                  <span className="line-badge">{r.shortName}</span>
                  <span>
                    {action ? t(`plan.${action}`) : ""}
                    {action ? " · " : ""}
                    {lostNames > 0 && <span className="st-lost">{t("plan.affectedRows", { count: lostNames })}</span>}
                    {lostNames > 0 && unsure > 0 ? " · " : ""}
                    {unsure > 0 && <span className="st-unsure">{t("plan.unsureRows", { count: unsure })}</span>}
                  </span>
                  <span aria-hidden="true" className="muted" style={{ marginLeft: "auto" }}>
                    {isOpen ? "−" : "+"}
                  </span>
                </button>
                {myGroups.map((g) => (
                  <Question
                    key={g.id}
                    g={g}
                    line={r.shortName}
                    busy={saving === g.id}
                    onChoose={(lost) => void choose(g, lost)}
                  />
                ))}
                {isOpen && network.data && (
                  <LineSchema stops={lineSchema(network.data, r.routeId, rows)} label={`${t("plan.lines")}: ${r.shortName}`} />
                )}
              </li>
            );
          })}
        </ul>
        <p className="small muted" style={{ marginTop: "var(--sp-2)" }}>
          {t("plan.schemaNote")}
        </p>
        {saveError && <p className="error-msg">{saveError}</p>}
      </section>

      <details>
        <summary>{t("details")}</summary>
        <Details closure={c} impact={impact.data} />
        <PlanDetails closureId={closureId} />
      </details>
    </Panel>
  );
}

function Question({ g, line, busy, onChoose }: { g: Group; line: string; busy: boolean; onChoose: (lost: boolean) => void }) {
  const { t } = useTranslation();
  const st = groupState(g);
  const [editing, setEditing] = useState(false);
  const text = g.question ? tr(g.question) : t("plan.questionDefault", { line, count: g.rows.length });
  if ((st === "lost" || st === "served") && !editing) {
    return (
      <p className="small" style={{ marginTop: "var(--sp-1)" }}>
        <span className={st === "lost" ? "st-lost" : "st-ok"}>{t(st === "lost" ? "plan.decidedLost" : "plan.decidedServed")}</span>{" "}
        ({g.rows.length}) ·{" "}
        <button type="button" className="linklike" onClick={() => setEditing(true)}>
          {t("plan.change")}
        </button>
      </p>
    );
  }
  return (
    <div className="question">
      <p>{text}</p>
      {g.reason && (
        <details className="small">
          <summary>{t("plan.why")}</summary>
          <p className="muted">{tr(g.reason)}</p>
        </details>
      )}
      <div className="choice">
        <button type="button" className="btn" disabled={busy} aria-pressed={st === "lost"} onClick={() => { setEditing(false); onChoose(true); }}>
          {t("plan.yesLost")}
          {g.suggestedLost && <span className="small"> ({t("plan.suggested")})</span>}
        </button>
        <button type="button" className="btn" disabled={busy} aria-pressed={st === "served"} onClick={() => { setEditing(false); onChoose(false); }}>
          {t("plan.noServed")}
        </button>
      </div>
      {busy && <p className="state-msg small" role="status">{t("plan.saving")}</p>}
    </div>
  );
}

function Details({ closure, impact }: { closure: Closure; impact?: Impact }) {
  const { t } = useTranslation();
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-3)" }}>
      {impact && (
        <table className="table">
          <caption className="visually-hidden">{t("plan.byZone")}</caption>
          <thead>
            <tr>
              <th>{t("plan.zone")}</th>
              <th className="num">{t("plan.stops")}</th>
              <th className="num">{t("plan.departures")}</th>
              <th className="num">{t("plan.residents")}</th>
            </tr>
          </thead>
          <tbody>
            {impact.byZone.map((z) => (
              <tr key={z.slug}>
                <td>{z.name}</td>
                <td className="num"><Figure inline value={z.stopsSuspended} provenance={impact.provenance} /></td>
                <td className="num"><Figure inline value={z.departuresLost} provenance={impact.provenance} /></td>
                <td className="num"><Figure inline value={z.residentsLosingStop} provenance={impact.provenance} method={tr(impact.method)} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {impact && <p className="small muted">{tr(impact.method)}</p>}
      {closure.sourceUrl && (
        <p className="small">
          <a href={closure.sourceUrl} target="_blank" rel="noreferrer">
            {t("publish.openSource")}
          </a>
        </p>
      )}
    </div>
  );
}

/** One map point per stop: lost if any of its rows is lost, else unsure, else served. */
function stopsForMap(rows: AffectedStop[], t: (k: string) => string): MapStop[] {
  const byStop = new Map<string, AffectedStop[]>();
  for (const r of rows) byStop.set(r.stopId, [...(byStop.get(r.stopId) ?? []), r]);
  return [...byStop.values()].map((rs) => {
    const st = rs.map(rowStatus);
    const status = st.includes("lost") ? "lost" : st.includes("unsure") ? "unsure" : "served";
    const lines = [...new Set(rs.map((r) => r.routeShortName))].join(", ");
    const word = status === "lost" ? t("plan.srLost") : status === "unsure" ? t("plan.srUnsure") : t("plan.srServed");
    return {
      id: rs[0].stopId,
      name: rs[0].name,
      location: rs[0].location as [number, number],
      status,
      label: `${word} (${lines})`,
    };
  });
}
