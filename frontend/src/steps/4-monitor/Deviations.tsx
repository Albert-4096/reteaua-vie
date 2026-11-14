// R18: one row per off-route group in the diversion view. Kilometres, never money.
// An incomplete recording is said so, and an empty group list is not reported as zero.
import { useTranslation } from "react-i18next";
import {
  deviationTracks,
  DEVIATIONS_KEY,
  type DeviationGroup,
  type Deviations as DeviationReport,
} from "../../api/deviations";
import { Figure } from "../../components/Figure";
import { LoadState } from "../../components/Panel";
import { fmtWindow, tr } from "../../lib/format";
import { invalidate, type Resource } from "../../lib/store";
import "./deviations.css";

const copy = {
  title: { ro: "Abateri de la traseu", en: "Off-route runs" },
  window: { ro: "Fereastra înregistrării", en: "Recording window" },
  incomplete: {
    ro: "Înregistrarea este incompletă. Nu socotim lipsa grupurilor ca zero abateri.",
    en: "The recording is incomplete. We do not treat missing groups as zero deviations.",
  },
  empty: { ro: "Nicio abatere de la traseu în această fereastră.", en: "No off-route run in this window." },
  announced: { ro: "anunțată", en: "announced" },
  unannounced: { ro: "fără anunț, de verificat", en: "no notice, to be checked" },
  line: (name: string) => ({ ro: `Linia ${name}`, en: `Line ${name}` }),
  sens: (n: number) => ({ ro: `sens ${n}`, en: `direction ${n}` }),
  runs: { ro: "rulări", en: "runs" },
  extra: { ro: "în plus", en: "extra" },
  onMap: { ro: "Traseele înregistrate sunt desenate pe hartă.", en: "The recorded tracks are drawn on the map." },
  retry: { ro: "Reîncearcă", en: "Retry" },
};

function finite(n: number | null | undefined): number | null {
  return typeof n === "number" && Number.isFinite(n) ? n : null;
}

function methodText(data: DeviationReport) {
  return {
    ro: `Cel puțin ${data.thresholds.minReports} poziții la peste ${data.thresholds.offRouteMeters} m de orice traseu al liniei.`,
    en: `At least ${data.thresholds.minReports} positions more than ${data.thresholds.offRouteMeters} m from every shape of the line.`,
  };
}

/** Summary counts. Empty groups during an incomplete recording stay unknown. */
function summaryCount(data: DeviationReport, n: number): number | null {
  if (data.status === "inregistrare_incompleta" && data.groups.length === 0) return null;
  return finite(n);
}

function place(g: DeviationGroup, unknown: string): string {
  const street = g.street?.trim() || null;
  const near = g.nearStop?.trim() || null;
  if (street && near && street !== near) return `${street} · ${near}`;
  return street ?? near ?? unknown;
}

export function Deviations({ result }: { result: Resource<DeviationReport> }) {
  useTranslation();
  const data = result.data;
  return (
    <section className="deviations" aria-label={tr(copy.title)}>
      <h2>{tr(copy.title)}</h2>
      {!data ? (
        <>
          <LoadState loading={result.loading} pending={result.pending} error={result.error} />
          {result.error && (
            <button type="button" className="btn" onClick={() => invalidate(DEVIATIONS_KEY)}>
              {tr(copy.retry)}
            </button>
          )}
        </>
      ) : (
        <Body data={data} />
      )}
    </section>
  );
}

function Body({ data }: { data: DeviationReport }) {
  useTranslation();
  const method = tr(methodText(data));
  const drawn = deviationTracks(data).features.length > 0;
  return (
    <>
      <p className="small">
        {tr(copy.window)}: {fmtWindow(data.window)}
      </p>
      {data.status === "inregistrare_incompleta" && <p className="st-unsure">{tr(copy.incomplete)}</p>}
      <p className="small">
        <Figure inline value={summaryCount(data, data.counts.unannounced)} provenance={data.provenance} method={method} />{" "}
        {tr(copy.unannounced)}
        {" · "}
        <Figure inline value={summaryCount(data, data.counts.announced)} provenance={data.provenance} method={method} />{" "}
        {tr(copy.announced)}
      </p>
      {data.status === "ok" && data.groups.length === 0 ? (
        <p className="muted">{tr(copy.empty)}</p>
      ) : (
        data.groups.length > 0 && (
          <ul className="list small">
            {data.groups.map((g, index) => (
              <Group
                key={`${g.routeId}|${g.directionId ?? ""}|${g.street ?? ""}|${g.nearStop ?? ""}|${g.classification}|${index}`}
                group={g}
                provenance={data.provenance}
                method={method}
              />
            ))}
          </ul>
        )
      )}
      {drawn && <p className="small muted">{tr(copy.onMap)}</p>}
    </>
  );
}

function Group({
  group,
  provenance,
  method,
}: {
  group: DeviationGroup;
  provenance: DeviationReport["provenance"];
  method: string;
}) {
  const { t } = useTranslation();
  const announced = group.classification === "anuntata";
  const words =
    group.classification === "anuntata" ? copy.announced : group.classification === "fara_anunt" ? copy.unannounced : null;
  return (
    <li>
      <strong>{group.shortName ? tr(copy.line(group.shortName)) : t("unknown")}</strong>
      {" · "}
      {place(group, t("unknown"))}
      {group.directionId != null && (
        <>
          {" · "}
          <span className="muted">{tr(copy.sens(group.directionId))}</span>
        </>
      )}
      <br />
      <span className={announced ? "st-ok" : "st-unsure"}>{words ? tr(words) : t("unknown")}</span>
      <br />
      <span className="muted">
        <Figure inline value={finite(group.runs)} provenance={provenance} method={method} /> {tr(copy.runs)}
        {" · "}
        <Figure inline value={finite(group.extraKm)} unit="km" digits={2} provenance={provenance} method={method} />{" "}
        {tr(copy.extra)}
      </span>
    </li>
  );
}
