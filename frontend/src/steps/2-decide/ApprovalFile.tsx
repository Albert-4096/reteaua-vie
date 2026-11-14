// N1: the approval file for the traffic commission. Hidden on screen; Ctrl+P (or the print button)
// prints only this page, on one A4 sheet. Every number carries [n], the index of its source and date.
// Only data the API already serves (D-011); a missing value prints „necunoscut”.
import { createPortal } from "react-dom";
import { api, type AffectedStop, type Analysis, type Closure, type Impact, type Network, type Provenance } from "../../api/client";
import { v2, type Conflict, type WindowSuggestion } from "../../api/v2";
import i18n from "../../i18n";
import { decisionGroups, groupCounts, groupState } from "../../lib/decisions";
import { fmtDateTime, fmtNumber, fmtWindow, tr } from "../../lib/format";
import { useResource } from "../../lib/store";
import { A } from "./strings";
import "./approval.css";

type Props = { closure: Closure; impact?: Impact; windows?: WindowSuggestion; hours: number };

/** Numbers the sources in the order the page cites them; the same source and version gets one number. */
class Sources {
  list: Provenance[] = [];
  cite(ps: Provenance[] | null | undefined): string {
    const ids = (ps ?? []).map((p) => {
      let i = this.list.findIndex((q) => q.source === p.source && q.version === p.version);
      if (i < 0) i = this.list.push(p) - 1;
      return i + 1;
    });
    return ids.length ? `[${[...new Set(ids)].join(", ")}]` : "";
  }
}

/** The row counts as lost the same way the backend counts it: certain and not unticked, or unsure and ticked. */
const isLost = (r: AffectedStop) => (r.state === "affected" ? r.confirmed !== false : r.confirmed === true);

/** Bilingual backend notes read „ro / en”; print the half for the current language. */
function half(s: string): string {
  const [ro, en] = s.split(" / ");
  return i18n.language === "en" && en ? en : ro;
}

function Num({ value, cite }: { value: number | null | undefined; cite: string }) {
  return (
    <>
      <span className="af-num">{fmtNumber(value) ?? i18n.t("unknown")}</span>
      {cite && <span className="af-cite"> {cite}</span>}
    </>
  );
}

export function ApprovalFile({ closure: c, impact, windows: w, hours }: Props) {
  const analysis = useResource<Analysis>(`analysis:${c.id}`, () => api.analysis(c.id));
  const conflicts = useResource<Conflict[]>(`conflicts:${c.id}`, () => v2.conflicts(c.id));
  const net = useResource<Network>("network", () => api.network());
  const short = (rid: string) => net.data?.routes.find((x) => x.id === rid)?.shortName ?? rid;
  const byNum = (x: string, y: string) => x.localeCompare(y, "ro", { numeric: true });

  const src = new Sources();
  const a = analysis.data;
  const t = impact?.totals;
  const impactCite = src.cite(impact?.provenance);
  const undecided = a ? a.stops.filter((r) => r.state === "unsure" && r.confirmed == null).length : 0;

  // Stops lost, one line per route: unique names in route order, and the departures lost on them.
  const perLine = new Map<string, { names: string[]; departures: number | null }>();
  for (const r of a?.stops ?? []) {
    if (!isLost(r)) continue;
    const cur = perLine.get(r.routeShortName) ?? { names: [], departures: 0 };
    if (!cur.names.includes(r.name)) cur.names.push(r.name);
    cur.departures = cur.departures === null || r.departuresLost === null ? null : cur.departures + r.departuresLost;
    perLine.set(r.routeShortName, cur);
  }
  const analysisCite = src.cite(a?.provenance);

  const best = w ? [...w.candidates].sort((x, y) => x.rank - y.rank)[0] : undefined;
  const windowsCite = src.cite(w?.provenance);

  // One conflict row per other closure, with its kinds of overlap and the lines involved.
  const byOther = new Map<string, { c: Conflict; kinds: string[]; routes: Set<string> }>();
  for (const k of conflicts.data ?? []) {
    const cur = byOther.get(k.otherClosureId) ?? { c: k, kinds: [], routes: new Set<string>() };
    cur.kinds.push(tr(A.kind[k.kind] ?? { ro: k.kind }));
    k.routeIds.forEach((rid) => cur.routes.add(short(rid)));
    byOther.set(k.otherClosureId, cur);
  }

  const groups = a ? decisionGroups(a) : [];
  const certain = a ? a.stops.filter((r) => r.state === "affected") : [];
  const overridden = certain.filter((r) => r.confirmed === false).length;

  // One phrase per route change; the two directions merge when the notice says the same for both.
  const merged = new Map<string, { ra: NonNullable<Closure["routeActions"]>[number]; dirs: number[] }>();
  for (const ra of c.routeActions ?? []) {
    const key = `${ra.routeId}|${ra.action}|${(ra.stopNames ?? []).join("|")}`;
    const cur = merged.get(key) ?? { ra, dirs: [] };
    if (ra.directionId !== null && ra.directionId !== undefined) cur.dirs.push(ra.directionId);
    merged.set(key, cur);
  }
  const actions = [...merged.values()].map(({ ra, dirs }) => {
    const dir = dirs.length === 1 ? ` (${tr(A.dir(dirs[0]))})` : "";
    const via = ra.stopNames && ra.stopNames.length > 0 ? `: ${ra.stopNames.join(" – ")}` : "";
    return `${tr(A.line(short(ra.routeId)))} ${tr(A.action[ra.action] ?? { ro: ra.action })}${dir}${via}`;
  });
  const temps = (c.temporaryRoutes ?? []).map((tr0) => tr(A.tempRoute(tr0.shortName, tr0.streets.join(" – "))));

  return createPortal(
    <article className="approval-file" lang={i18n.language === "en" ? "en" : "ro"}>
      <header className="af-head">
        <h1>{tr(A.title)}</h1>
        <p>{tr(A.printedAt(fmtDateTime(new Date().toISOString()), c.id))}</p>
      </header>

      <section>
        <h2>{tr(A.works)}</h2>
        <p className="af-lead">{tr(c.title)}</p>
        <dl className="af-dl">
          {c.locationNote && (
            <>
              <dt>{tr(A.where)}</dt>
              <dd>{tr(c.locationNote)}</dd>
            </>
          )}
          <dt>{tr(A.when)}</dt>
          <dd>{fmtWindow(c.window)}</dd>
          {(actions.length > 0 || temps.length > 0) && (
            <>
              <dt>{tr(A.lines)}</dt>
              <dd>{[...actions, ...temps].join("; ")}</dd>
            </>
          )}
          {c.sourceUrl && (
            <>
              <dt>{tr(A.notice)}</dt>
              <dd className="af-url">{c.sourceUrl}</dd>
            </>
          )}
        </dl>
      </section>

      {undecided > 0 && <p className="af-warn">{tr(A.undecided(undecided))}</p>}

      <section>
        <h2>{tr(A.loss)}</h2>
        <div className="af-figs">
          <div>
            <Num value={t?.departuresLost} cite={impactCite} />
            <span>{tr(A.departures)}</span>
          </div>
          <div>
            <Num value={t?.residentsLosingStop} cite={impactCite} />
            <span>{tr(A.residents)}</span>
          </div>
          <div>
            <Num value={t?.stopsSuspended} cite={impactCite} />
            <span>{tr(A.suspended)}</span>
          </div>
          <div>
            <Num value={t?.routesAffected} cite={impactCite} />
            <span>{tr(A.routes)}</span>
          </div>
        </div>
      </section>

      <section>
        <h2>{tr(A.stops)}</h2>
        {!a ? (
          <p>{i18n.t("unknown")}</p>
        ) : perLine.size === 0 ? (
          <p>{tr(A.stopsNone)}</p>
        ) : (
          [...perLine.entries()]
            .sort(([x], [y]) => byNum(x, y))
            .map(([line, v]) => (
              <p key={line} className="af-line">
                <strong>{tr(A.stopsLine(line, v.names.length))}</strong>
                {" · "}
                <Num value={v.departures} cite={analysisCite} /> {tr(A.departuresShort)}
                <br />
                {v.names.join(", ")}
              </p>
            ))
        )}
      </section>

      <section>
        <h2>{tr(A.window)}</h2>
        <table className="af-table">
          <thead>
            <tr>
              <th />
              <th />
              <th className="num">{tr(A.departures)}</th>
              <th className="num">{tr(A.residents)}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{tr(A.windowNotice)}</td>
              <td>{fmtWindow(c.window)}</td>
              <td className="num">
                <Num value={t?.departuresLost} cite={impactCite} />
              </td>
              <td className="num">
                <Num value={t?.residentsLosingStop} cite={impactCite} />
              </td>
            </tr>
            <tr>
              <td>{tr(A.windowBest(hours))}</td>
              {best ? (
                <>
                  <td>{fmtWindow(best.window)}</td>
                  <td className="num">
                    <Num value={best.departuresLost} cite={windowsCite} />
                  </td>
                  <td className="num">
                    <Num value={best.residentsLosingStop} cite={windowsCite} />
                  </td>
                </>
              ) : (
                <td colSpan={3}>{tr(A.windowPending)}</td>
              )}
            </tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>{tr(A.conflicts)}</h2>
        {!conflicts.data ? (
          <p>{i18n.t("unknown")}</p>
        ) : byOther.size === 0 ? (
          <p>{tr(A.conflictsNone)}</p>
        ) : (
          <ul className="af-list">
            {[...byOther.values()].map(({ c: k, kinds, routes }) => (
              <li key={k.otherClosureId}>
                {tr(k.otherTitle)} · {kinds.join(", ")} · {fmtWindow(k.overlap)} · {tr(A.linesShort)}{" "}
                {[...routes].sort(byNum).join(", ")}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2>{tr(A.decisions)}</h2>
        {!a ? (
          <p>{i18n.t("unknown")}</p>
        ) : (
          <>
            <p>
              {tr(A.certain(certain.length))} {overridden > 0 && tr(A.overridden(overridden))}
            </p>
            {groups.length === 0 ? (
              <p>{tr(A.noQuestions)}</p>
            ) : (
              <ul className="af-list">
                {groups.map((g) => {
                  const n = groupCounts(g);
                  return (
                    <li key={g.id}>
                      <span className="af-box" aria-hidden="true">
                        {n.open === 0 ? "☑" : "☐"}
                      </span>{" "}
                      {g.question ? tr(g.question) : tr(A.line(short(g.routeId)))} <strong>{tr(A.answer[groupState(g)])}</strong>
                      {" · "}
                      {tr(A.rows(n.lost, n.served, n.open))}
                    </li>
                  );
                })}
              </ul>
            )}
          </>
        )}
      </section>

      <section className="af-sources">
        <h2>{tr(A.sources)}</h2>
        <ol>
          {src.list.map((p, i) => (
            <li key={i}>
              {p.source}
              {p.version ? ` ${p.version}` : ""}, {tr(A.fetched(fmtDateTime(p.fetchedAt)))}
              {p.note ? `. ${half(p.note)}` : ""}
            </li>
          ))}
        </ol>
        {impact && (
          <p>
            <strong>{tr(A.method)}:</strong> {tr(impact.method)}
          </p>
        )}
      </section>

      <footer className="af-verdict">
        <p>
          <strong>{tr(A.verdict)}:</strong> <span className="af-box">☐</span> {tr(A.approveNotice)}{" "}
          <span className="af-box">☐</span> {tr(A.approveBest)} <span className="af-box">☐</span> {tr(A.reject)}
        </p>
        <p className="af-sign">
          <span>{tr(A.signature)}</span>
          <span>{tr(A.date)}</span>
        </p>
      </footer>
    </article>,
    document.body,
  );
}
