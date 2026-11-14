// Step 2 Decizi: „Care variantă? Când?” The best windows (top 3), the two prepared options side by side, „Confirmă”.
import { useTranslation } from "react-i18next";
import { api, type Closure, type Impact } from "../../api/client";
import { v2, type Scenario, type ScenarioCompare, type ScenarioImpact, type WindowSuggestion } from "../../api/v2";
import { CasePicker } from "../../components/CasePicker";
import { Figure } from "../../components/Figure";
import { DetourCost } from "../../components/DetourCost";
import { useMapOverlay } from "../../components/MapView";
import { LoadState, Panel } from "../../components/Panel";
import i18n from "../../i18n";
import { tr } from "../../lib/format";
import { navigate, stepHref } from "../../lib/router";
import { useResource } from "../../lib/store";
import type { StepProps } from "../types";
import { ApprovalFile } from "./ApprovalFile";
import { EventConflicts } from "./EventConflicts";
import { KmRows } from "./KmRows";
import { A, S } from "./strings";

export function DecideStep(props: StepProps) {
  if (!props.closureId) return <CasePicker step={2} />;
  return <Decide {...props} closureId={props.closureId} />;
}

function Decide({ closureId, caseKey }: StepProps & { closureId: string }) {
  const { t } = useTranslation();
  const closure = useResource<Closure>(`closure:${closureId}`, () => api.closure(closureId));
  const impact = useResource<Impact>(`impact:${closureId}`, () => api.impact(closureId));
  const c = closure.data;
  const hours = c ? Math.max(1, Math.round((Date.parse(c.window.end) - Date.parse(c.window.start)) / 3_600_000)) : null;
  const windows = useResource<WindowSuggestion>(hours ? `windows:${closureId}:${hours}` : null, (onPending) =>
    v2.windows(closureId, hours!, onPending),
  );
  const scenarios = useResource<Scenario[]>(`scenarios:${closureId}`, () => v2.scenarios(closureId));
  const pair = (scenarios.data ?? []).filter((s) => s.mitigations.length > 0).slice(0, 2);
  const compare = useResource<ScenarioCompare>(
    // The closure id is in the key so a decision in step 1 can drop it (T15).
    pair.length === 2 ? `compare:${closureId}:${pair[0].id}:${pair[1].id}` : null,
    (onPending) => v2.compare(pair[0].id, pair[1].id, onPending),
  );

  useMapOverlay(
    {
      closure: (c?.geometry as GeoJSON.Geometry | null) ?? null,
      highlightRouteIds: c?.routeIds ?? [],
      fitKey: c ? `decide:${closureId}` : undefined,
    },
    [c, closureId],
  );

  if (!c || !hours) {
    return (
      <Panel title={tr(S.title)}>
        <LoadState loading={closure.loading} error={closure.error} />
      </Panel>
    );
  }

  const w = windows.data;
  const top = w ? [...w.candidates].sort((a, b) => a.rank - b.rank) : [];
  return (
    <Panel
      title={tr(S.title)}
      sentence={tr(S.sentence(hours))}
      foot={
        <div style={{ display: "flex", gap: "var(--sp-2)" }}>
          <button type="button" className="btn btn-primary" onClick={() => navigate(stepHref(3, caseKey))}>
            {tr(S.confirm)}
          </button>
          <button
            type="button"
            className="btn"
            style={{ whiteSpace: "nowrap", flex: "none" }}
            title={tr(A.printHint)}
            onClick={() => window.print()}
          >
            {tr(A.print)}
          </button>
        </div>
      }
    >
      <ApprovalFile closure={c} impact={impact.data} windows={w} hours={hours} />
      <section>
        <h2>{tr(S.windows)}</h2>
        {!w ? (
          <LoadState loading={windows.loading} pending={windows.pending} error={windows.error} />
        ) : (
          <table className="table" style={{ marginTop: "var(--sp-2)" }}>
            <thead>
              <tr>
                <th>{tr(S.window)}</th>
                <th className="num">{tr(S.lost)}</th>
              </tr>
            </thead>
            <tbody>
              {top.slice(0, 3).map((k) => (
                <tr key={k.rank}>
                  <td>{shortWindow(k.window)}</td>
                  <td className="num">
                    <Figure inline value={k.departuresLost} provenance={w.provenance} method={tr(w.method)} />
                  </td>
                </tr>
              ))}
              <tr>
                <td className="muted">
                  {shortWindow(c.window)} ({tr(S.noticeWindow)})
                </td>
                <td className="num">
                  <Figure inline value={impact.data?.totals.departuresLost} provenance={impact.data?.provenance} method={impact.data ? tr(impact.data.method) : null} />
                </td>
              </tr>
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h2>{tr(S.compare)}</h2>
        {scenarios.data && pair.length < 2 ? (
          <p className="muted">{tr(S.noScenarios)}</p>
        ) : !compare.data ? (
          <LoadState
            loading={scenarios.loading || compare.loading}
            pending={compare.pending}
            error={scenarios.error ?? compare.error}
          />
        ) : (
          <CompareTable a={compare.data.a} b={compare.data.b} titles={pair.map((s) => tr(s.title))} />
        )}
      </section>

      <EventConflicts closureId={closureId} />
      <KmRows closureId={closureId} />
      <DetourCost closureId={closureId} />

      <details>
        <summary>{t("details")}</summary>
        {w && top.length > 3 && (
          <>
            <h3>{tr(S.moreWindows)}</h3>
            <table className="table" style={{ marginTop: "var(--sp-1)" }}>
              <tbody>
                {top.slice(3).map((k) => (
                  <tr key={k.rank}>
                    <td>{shortWindow(k.window)}</td>
                    <td className="num">
                      <Figure inline value={k.departuresLost} provenance={w.provenance} method={tr(w.method)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        {w && (
          <>
            <h3 style={{ marginTop: "var(--sp-3)" }}>{tr(S.method)}</h3>
            <p className="small">{tr(w.method)}</p>
          </>
        )}
        {compare.data && (
          <>
            <h3 style={{ marginTop: "var(--sp-3)" }}>{tr(S.notes)}</h3>
            {[compare.data.a, compare.data.b].map((si, i) => (
              <div key={si.scenarioId} style={{ marginTop: "var(--sp-2)" }}>
                <p className="small">
                  <strong>{pair[i] ? tr(pair[i].title) : si.scenarioId}</strong>
                </p>
                <ul className="small" style={{ margin: 0, paddingLeft: "var(--sp-4)" }}>
                  {(si.notes ?? []).map((n, j) => (
                    <li key={j}>{tr(n.text)}</li>
                  ))}
                </ul>
              </div>
            ))}
          </>
        )}
        <h3 style={{ marginTop: "var(--sp-3)" }}>{tr(S.whatIf)}</h3>
        <p className="small">{tr(S.whatIfText)}</p>
      </details>
    </Panel>
  );
}

function CompareTable({ a, b, titles }: { a: ScenarioImpact; b: ScenarioImpact; titles: string[] }) {
  const rows: { label: string; pick: (s: ScenarioImpact) => number | null | undefined; method?: (s: ScenarioImpact) => string | null }[] = [
    { label: tr(S.rowLost), pick: (s) => s.summary.departuresLost, method: (s) => tr(s.impact.method) },
    { label: tr(S.rowStop), pick: (s) => s.summary.residentsLosingStop, method: (s) => tr(s.impact.method) },
    {
      label: tr(S.rowAccess),
      pick: (s) => s.summary.residentsLosingAccess,
      method: (s) => (s.access ? tr(s.access.method) : null),
    },
  ];
  return (
    <table className="table" style={{ marginTop: "var(--sp-2)", tableLayout: "fixed" }}>
      <thead>
        <tr>
          <td style={{ width: "40%" }} />
          {titles.map((t) => (
            <th key={t} style={{ textAlign: "right" }}>
              {t}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.label}>
            <td>{r.label}</td>
            {[a, b].map((s) => (
              <td key={s.scenarioId} className="num">
                <Figure inline value={r.pick(s)} provenance={s.provenance} method={r.method?.(s)} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** „sâm. 14 nov., 22:30 – dum. 15 nov., 06:30”: short enough for one table line. */
function shortWindow(w: { start: string; end: string }): string {
  const loc = i18n.language === "en" ? "en-GB" : "ro-RO";
  const f = (iso: string, o: Intl.DateTimeFormatOptions) =>
    new Intl.DateTimeFormat(loc, { timeZone: "Europe/Bucharest", ...o }).format(new Date(iso));
  const day = (iso: string) => f(iso, { weekday: "short", day: "numeric", month: "short" });
  const time = (iso: string) => f(iso, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  if (day(w.start) === day(w.end)) return `${day(w.start)}, ${time(w.start)}–${time(w.end)}`;
  return `${day(w.start)}, ${time(w.start)} – ${day(w.end)}, ${time(w.end)}`;
}
