// R5 in step 2: one row per line that loses part of its route.
// „Tramvai 4: 54 curse × 8,8 km nefăcuți (≈ 473 km) · 4b: necunoscut · pe jos între capete: necunoscut”. Km only, never money.
import { km, kmCsvPath, type KmLine, type KmReport, type KmTemporary } from "../../api/km";
import { Figure } from "../../components/Figure";
import { LoadState } from "../../components/Panel";
import { tr } from "../../lib/format";
import { useResource } from "../../lib/store";
import { K } from "./strings";

type Row = {
  key: string;
  mode: string;
  shortName: string;
  trips: number | null;
  kmPerTrip: number | null;
  kmNotRun: number | null;
  temporary: KmTemporary[];
  walkMinutes: number | null;
};

/** One row per (mode, line): both directions summed. A temporary line „4b” goes with line „4”. */
function toRows(r: KmReport): Row[] {
  const groups = new Map<string, KmLine[]>();
  for (const ln of r.lines) {
    const k = `${ln.mode}:${ln.shortName}`;
    groups.set(k, [...(groups.get(k) ?? []), ln]);
  }
  return [...groups.entries()].map(([key, ls]) => {
    const known = ls.every((l) => l.trips !== null && l.kmNotRun !== null);
    const trips = known ? ls.reduce((s, l) => s + l.trips!, 0) : null;
    const total = known ? ls.reduce((s, l) => s + l.kmNotRun!, 0) : null;
    const short = ls[0].shortName;
    const walks = r.walkBetweenEnds.filter((w) => w.shortName === short).map((w) => w.minutes);
    return {
      key,
      mode: ls[0].mode,
      shortName: short,
      trips,
      kmPerTrip: trips && total !== null ? total / trips : Math.max(...ls.map((l) => l.sectionKm)),
      kmNotRun: total,
      temporary: r.temporary.filter((t) => t.replacesRouteId ? ls.some((l) => l.routeId === t.replacesRouteId) : new RegExp(`^${short}[a-z]$`, "i").test(t.shortName)),
      walkMinutes: walks.length ? Math.max(...walks) : null,
    };
  });
}

export function KmRows({ closureId }: { closureId: string }) {
  const res = useResource<KmReport>(`km:${closureId}`, () => km(closureId));
  const r = res.data;
  const methodKm = tr(K.methodKm);
  return (
    <section>
      <h2>{tr(K.title)}</h2>
      <a className="small" href={kmCsvPath(closureId)}>{tr({ ro: "Descarcă kilometrii pentru SMTT (CSV)", en: "Download kilometres for SMTT (CSV)" })}</a>
      {!r ? (
        <LoadState loading={res.loading} error={res.error} />
      ) : r.lines.length === 0 ? (
        <p className="muted">{tr(K.none)}</p>
      ) : (
        <>
          <ul className="list" style={{ marginTop: "var(--sp-2)" }}>
            {toRows(r).map((row) => (
              <li key={row.key}>
                <strong>
                  {tr(K.mode[row.mode] ?? { ro: row.mode, en: row.mode })} {row.shortName}
                </strong>
                {": "}
                <Figure inline value={row.trips} provenance={r.provenance} method={methodKm} /> {tr(K.trips)} ×{" "}
                <Figure inline value={row.kmPerTrip} digits={1} provenance={r.provenance} method={methodKm} />{" "}
                {tr(K.perTrip)} (≈ <Figure inline value={row.kmNotRun} unit="km" provenance={r.provenance} method={methodKm} />)
                {row.temporary.map((t) => (
                  <span key={t.shortName}>
                    {" · "}
                    {t.shortName}: <Figure inline value={t.kmRun} unit="km" provenance={r.provenance} method={tr(t.note)} />
                  </span>
                ))}
                {" · "}
                {tr(K.walk)}:{" "}
                <Figure inline value={row.walkMinutes} unit="min" provenance={r.provenance} method={tr(K.methodWalk)} />
              </li>
            ))}
          </ul>
          <p className="small muted" style={{ marginTop: "var(--sp-1)" }}>
            {tr(K.source(r.timetableVersion))}
          </p>
        </>
      )}
    </section>
  );
}
