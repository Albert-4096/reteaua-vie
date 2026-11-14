// S1-F: in the CityApp mock-up, a tap on the stop asks GET /api/stops/{stopId}/status and shows the answer.
// The type is local (only the fields shown here) until schema.d.ts is regenerated with StopStatus (CONTRACT v2.12).
// liveFeed („în lucru” until O2) is left out: in a 300 px phone it takes three lines for a check that does not run yet.
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { accessibility, type StopAccessibility } from "../../api/accessibility";
import { apiGet, type I18n, type Provenance } from "../../api/client";
import { Figure } from "../../components/Figure";
import { fmtDate, tr } from "../../lib/format";
import { useResource } from "../../lib/store";
import { S } from "./strings";
import "./stopStatus.css";

type Action = "suspended" | "shortened" | "rerouted";
type StopLine = {
  shortName: string;
  stops: "yes" | "no" | "unconfirmed" | "novehicle";
  reason: { title: I18n | null; action: Action | null; noticeUrl: string | null } | null;
};
type StopStatus = {
  stopId: string;
  name: string;
  lines: StopLine[];
  sentence: I18n;
  provenance: Provenance[];
};

export function StopStatusTap({ stopId, name }: { stopId: string; name: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const status = useResource<StopStatus>(open ? `stopStatus:${stopId}` : null, () =>
    apiGet<StopStatus>(`/api/stops/${encodeURIComponent(stopId)}/status`),
  );
  // R6: the typical wait for a step-free vehicle, from our recording; the line is left out when the API has none.
  const acc = useResource<StopAccessibility>(open ? `accessibility:stop:${stopId}` : null, () => accessibility.stop(stopId));
  const answerId = `stop-answer-${stopId}`;
  return (
    <div className="stop-tap">
      <p className="small muted">{tr(S.stopStatus.label)}</p>
      <button type="button" className="row-button" aria-expanded={open} aria-controls={answerId} onClick={() => setOpen(!open)}>
        <strong>{name}</strong>
        <span aria-hidden="true" className="muted" style={{ marginLeft: "auto" }}>
          {open ? "−" : "+"}
        </span>
      </button>
      {open && (
        <div id={answerId} className="stop-answer" aria-live="polite">
          {status.data ? (
            <Answer s={status.data} acc={acc.data} />
          ) : status.error ? (
            <p className="small">{status.error.message || t("unknown")}</p>
          ) : (
            <p className="small muted" role="status">
              {t("loading")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function Answer({ s, acc }: { s: StopStatus; acc?: StopAccessibility }) {
  // One entry per line that does not stop here (the API lists each direction).
  const notStopping = new Map<string, StopLine>();
  for (const l of s.lines) if (l.stops !== "yes" && !notStopping.has(l.shortName)) notStopping.set(l.shortName, l);
  const titles = [...new Set([...notStopping.values()].map((l) => tr(l.reason?.title)).filter(Boolean))];
  const notices = new Set(s.lines.map((l) => l.reason?.noticeUrl).filter(Boolean));
  const sources = s.provenance.filter((p) => p.url && notices.has(p.url));
  if (!sources.length && s.provenance.length) sources.push(s.provenance[s.provenance.length - 1]);
  return (
    <>
      <p>{tr(s.sentence)}</p>
      {acc && (
        <div className="small muted">
          <p>{tr(S.stopStatus.stepFree)}: <Figure inline value={acc.stepFreeWaitMin} unit="min" digits={1} provenance={acc.provenance} method={tr(acc.method)} /></p>
          <p>{tr(acc.recording.label)} · {tr(acc.caveat)}</p>
        </div>
      )}
      {notStopping.size > 0 && (
        <ul className="stop-answer-lines">
          {[...notStopping.values()].map((l) => (
            <li key={l.shortName}>
              <span className="line-chip">{l.shortName}</span>{" "}
              <span className="st-lost">{tr(actionText(l))}</span>
            </li>
          ))}
        </ul>
      )}
      {titles.map((x) => (
        <p key={x} className="small">
          {x}
        </p>
      ))}
      {sources.map((p) => (
        <p key={p.source} className="small muted">
          {tr(S.stopStatus.source)}:{" "}
          {p.url ? (
            <a href={p.url} target="_blank" rel="noreferrer">
              {p.source}
            </a>
          ) : (
            p.source
          )}
          {p.version ? ` ${p.version}` : ""}
          {p.fetchedAt ? `, ${fmtDate(p.fetchedAt)}` : ""}
        </p>
      ))}
    </>
  );
}

function actionText(l: StopLine): I18n {
  if (l.stops === "novehicle") return S.stopStatus.noVehicle;
  if (l.stops === "unconfirmed") return S.stopStatus.unconfirmed;
  const a = l.reason?.action;
  return a ? S.stopStatus.action[a] : S.stopStatus.noStop;
}
