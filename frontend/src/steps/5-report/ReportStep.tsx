// Step 5 Raportezi: „Ce trimitem la UE?” What our exports cover of each obligation, with the files as links.
// History, indicators and the full export list sit under „Detalii”.
import { useTranslation } from "react-i18next";
import { v2, type ComplianceReport, type ExportFile, type HistoryRow, type IndicatorSet } from "../../api/v2";
import { Figure } from "../../components/Figure";
import { LoadState, Panel } from "../../components/Panel";
import { fmtDate, fmtWindow, tr } from "../../lib/format";
import { useResource } from "../../lib/store";
import type { StepProps } from "../types";
import { AccessibleLines } from "./AccessibleLines";
import { DataQuality } from "./DataQuality";
import { S } from "./strings";

const NAP = "/api/exports/nap-metadata.json";
const ST_CLASS = { covered: "st-ok", partial: "st-unsure", missing: "st-lost" } as const;

/** Export URLs carry the public base URL; link the path so the file opens on whichever host serves the app. */
const localPath = (url: string) => {
  try {
    return new URL(url).pathname;
  } catch {
    return url;
  }
};

export function ReportStep(_props: StepProps) {
  const { t } = useTranslation();
  const compliance = useResource<ComplianceReport>("compliance", () => v2.compliance());
  const exports = useResource<ExportFile[]>("exports", () => v2.exports());
  const history = useResource<HistoryRow[]>("history", () => v2.history());
  const indicators = useResource<IndicatorSet>("indicators", () => v2.indicators());

  const c = compliance.data;
  const fileUrl = (name: string) => exports.data?.find((e) => e.name === name)?.url;

  return (
    <Panel
      title={tr(S.title)}
      sentence={tr(S.sentence)}
      foot={
        <a
          className="btn btn-primary"
          style={{ display: "block", textAlign: "center", textDecoration: "none" }}
          href={NAP}
          download
        >
          {tr(S.nap)}
        </a>
      }
    >
      {!c ? (
        <LoadState loading={compliance.loading} error={compliance.error} />
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th style={{ width: "60%" }}>{tr(S.obligation)}</th>
              <th>{tr(S.status)}</th>
            </tr>
          </thead>
          <tbody>
            {c.obligations.map((o) => (
              <tr key={o.id}>
                <td>
                  {o.id}
                  <br />
                  <span className="muted">{o.act}</span>
                </td>
                <td>
                  <span className={ST_CLASS[o.status]}>{tr(S.st[o.status])}</span>
                  {o.coveredBy.length > 0 && <br />}
                  {o.coveredBy.map((name, i) => {
                    const url = fileUrl(name);
                    return (
                      <span key={name}>
                        {i > 0 && ", "}
                        {url ? <a href={localPath(url)}>{name}</a> : name}
                      </span>
                    );
                  })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <AccessibleLines />
      <DataQuality />

      <details>
        <summary>{t("details")}</summary>

        <h3>{tr(S.history)}</h3>
        {!history.data ? (
          <LoadState loading={history.loading} error={history.error} />
        ) : (
          <ul className="list small" style={{ marginTop: "var(--sp-1)" }}>
            {history.data.map((h) => {
              const backfilled = h.closureId.startsWith("stpt_");
              return (
                <li key={h.closureId}>
                  {tr(h.title)}
                  <br />
                  <span className="muted">
                    {fmtWindow(h.window)} · {backfilled ? tr(S.backfilled) : tr(S.viaPlatform)}
                    {h.sourceUrl && (
                      <>
                        {" · "}
                        <a href={h.sourceUrl} target="_blank" rel="noreferrer">
                          {tr(S.source)}
                        </a>
                      </>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        )}

        <h3 style={{ marginTop: "var(--sp-3)" }}>{tr(S.indicators)}</h3>
        {!indicators.data ? (
          <LoadState loading={indicators.loading} error={indicators.error} />
        ) : (
          <table className="table" style={{ marginTop: "var(--sp-1)" }}>
            <tbody>
              {indicators.data.indicators.map((i) => (
                <tr key={i.code}>
                  <td>{tr(i.name)}</td>
                  <td className="num">
                    <Figure inline value={i.value} unit={i.unit} provenance={indicators.data!.provenance} method={tr(i.method)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <h3 style={{ marginTop: "var(--sp-3)" }}>{tr(S.exports)}</h3>
        {!exports.data ? (
          <LoadState loading={exports.loading} error={exports.error} />
        ) : (
          <ul className="list small" style={{ marginTop: "var(--sp-1)" }}>
            {exports.data.map((e) => (
              <li key={e.name}>
                <a href={localPath(e.url)}>{e.name}</a> <span className="muted">· {e.standard}</span>
                {e.updatedAt && <span className="muted"> · {fmtDate(e.updatedAt)}</span>}
              </li>
            ))}
          </ul>
        )}
      </details>
    </Panel>
  );
}
