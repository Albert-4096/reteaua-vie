// R2-F: step 0 „Linii”. Only the lines that do not run normally, from GET /api/lines/status (published closures).
// Lines with the same state, end, notice and replacement share one row („M32 M36 … · deviată …”).
import { Fragment, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { LoadState } from "../../components/Panel";
import {
  L,
  linesStatus,
  SEVERITY,
  stateClass,
  stateLabel,
  untilText,
  type LineStatus,
  type LinesStatus as Status,
} from "../../api/linesStatus";
import { fmtDate, fmtDateTime, tr } from "../../lib/format";
import { useResource } from "../../lib/store";
import "./linesStatus.css";

export function LinesStatus() {
  useTranslation();
  const res = useResource<Status>("linesStatus", () => linesStatus());
  const s = res.data;
  return (
    <section className="lines-status">
      <h2>{tr(L.title)}</h2>
      {!s ? (
        <LoadState loading={res.loading} error={res.error} />
      ) : (
        <Body s={s} />
      )}
    </section>
  );
}

function Body({ s }: { s: Status }) {
  const off = s.lines.filter((l) => l.state !== "normala" || l.serviceConfirmation);
  if (!off.length) return <p className="muted">{tr(L.allNormal)}</p>;

  const groups = new Map<string, LineStatus[]>();
  for (const l of [...off].sort((a, b) => SEVERITY.indexOf(a.state) - SEVERITY.indexOf(b.state))) {
    const k = [l.state, l.until, l.notice?.postId, l.replacedBy.join(","), l.directionIds?.join(","), l.closureId, l.serviceConfirmation?.label.ro].join("|");
    groups.set(k, [...(groups.get(k) ?? []), l]);
  }
  const replaced = (name: string) => off.filter((l) => l.replacedBy.includes(name)).map((l) => l.shortName);

  return (
    <>
      <p className="small muted">{tr(L.basis(fmtDateTime(s.at)))}</p>
      <ul className="list lines-status-list">
        {[...groups.values()].map((g) => {
          const l = g[0];
          const instead = l.state === "linie_temporara" ? replaced(l.shortName) : [];
          const bits: ReactNode[] = [];
          if (instead.length) bits.push(tr(L.insteadOf(instead.join(", "))));
          if (l.directionIds?.length === 1) bits.push(tr(L.oneDirection));
          if (l.replacedBy.length) bits.push(tr(L.replacedBy(l.replacedBy.join(", "))));
          if (l.notice?.postId)
            bits.push(
              l.notice.url ? (
                <a href={l.notice.url} target="_blank" rel="noreferrer" title={l.notice.title ?? undefined}>
                  {tr(L.notice(l.notice.postId))}
                </a>
              ) : (
                tr(L.notice(l.notice.postId))
              ),
            );
          return (
            <li key={g.map((x) => x.shortName).join(",")} title={l.source}>
              <span className="lines-status-chips">
                {g.map((x) => (
                  <span key={x.shortName} className="line-chip">
                    {x.shortName}
                  </span>
                ))}
              </span>{" "}
              <span>
                <span className={stateClass(l.state)}>{stateLabel(l)}</span>
                {l.until && ` ${tr(L.until(untilText(l.until, s.at)))}`}
                {l.serviceConfirmation && <><br /><span className="small">{tr(l.serviceConfirmation.label)}</span></>}
                {bits.map((b, i) => (
                  <Fragment key={i}> · {b}</Fragment>
                ))}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="small muted">
        {tr(L.source)}:{" "}
        {s.provenance.map((p, i) => (
          <Fragment key={i}>
            {i > 0 && "; "}
            {p.source}
            {p.version ? ` ${p.version}` : ""}
            {p.fetchedAt ? `, ${fmtDate(p.fetchedAt)}` : ""}
          </Fragment>
        ))}
      </p>
    </>
  );
}
