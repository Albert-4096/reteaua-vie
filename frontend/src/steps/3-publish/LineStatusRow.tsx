// R2-F: in the CityApp mock-up, one row for a saved line: „4 · suspendată, ia 4b”.
// It asks GET /api/lines/status?routeId= for each line of the alert, as CityApp would for a saved line,
// and shows the most affected one.
import { useTranslation } from "react-i18next";
import { L, linesStatus, SEVERITY, stateClass, stateLabel, untilText, type LineStatus } from "../../api/linesStatus";
import { fmtDateTime, tr } from "../../lib/format";
import { useResource } from "../../lib/store";

export function LineStatusRow({ routeIds, untilEnd = false }: { routeIds: string[]; untilEnd?: boolean }) {
  useTranslation();
  const key = routeIds.join(",");
  const res = useResource<{ at: string; line: LineStatus } | null>(key ? `lineStatusRow:${key}` : null, async () => {
    const all = await Promise.all(routeIds.map((r) => linesStatus(r)));
    const rows = all.flatMap((s, i) => s.lines.filter((l) => l.routeId === routeIds[i]).map((line) => ({ at: s.at, line })));
    rows.sort((a, b) => SEVERITY.indexOf(a.line.state) - SEVERITY.indexOf(b.line.state));
    return rows[0] ?? null;
  });
  const hit = res.data;
  if (!hit) return null;
  const l = hit.line;
  const tail =
    l.state === "normala"
      ? null
      : l.replacedBy.length
        ? tr(L.take(l.replacedBy.join(tr(L.or))))
        : untilEnd
          ? tr(L.untilEnd)
          : l.until
            ? tr(L.until(untilText(l.until, hit.at)))
            : null;
  return (
    <div>
      <p className="small muted">{tr(L.saved)}</p>
      <p>
        <span className="line-chip">{l.shortName}</span>{" "}
        <span className={stateClass(l.state)}>{l.state === "normala" ? tr(L.normal) : stateLabel(l)}</span>
        {tail && `, ${tail}`}
      </p>
      {l.serviceConfirmation && <p className="small">{tr(l.serviceConfirmation.label)}</p>}
      <details className="small muted"><summary>{tr(L.source)}</summary><p>{l.source}<br />{fmtDateTime(hit.at)}</p></details>
    </div>
  );
}
