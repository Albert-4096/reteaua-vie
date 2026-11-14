// The three outputs of step 3, each small: the notice side by side (D-013), the CityApp mock-up (T7-B), the stop.
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type Alert, type Analysis, type FeedValidation, type GeneratedNotice } from "../../api/client";
import { Figure } from "../../components/Figure";
import { LoadState } from "../../components/Panel";
import { fmtDate, fmtMeters, fmtTime, tr } from "../../lib/format";
import type { Resource } from "../../lib/store";
import { StopStatusTap } from "./stopStatus";

/** D-013: today's STPT text next to the notice the platform generates. */
export function NoticeView({ notice }: { notice: GeneratedNotice }) {
  const { t } = useTranslation();
  return (
    <div className="compare">
      <article>
        <h2>{t("publish.original")}</h2>
        {notice.sourceText ? <p className="notice-text">{notice.sourceText}</p> : <p className="muted">{t("publish.noSource")}</p>}
        {notice.sourceUrl && (
          <p className="small">
            <a href={notice.sourceUrl} target="_blank" rel="noreferrer">
              {t("publish.openSource")}
            </a>
          </p>
        )}
      </article>
      <article>
        <h2>
          {t("publish.generated")}
          {notice.status === "draft" && <span className="tag">{t("publish.draft")}</span>}
        </h2>
        <p className="notice-text">{tr(notice.text)}</p>
      </article>
    </div>
  );
}

/** Window end of an alert, or „până la finalizarea lucrărilor” when the alert says the end is open. */
export function untilText(a: Alert, t: (k: string) => string): string {
  if (/finalizarea lucrărilor/.test(a.descriptionText.ro)) return t("qr.untilEnd");
  const end = a.activePeriod[0]?.end;
  return end ? `${fmtTime(end)}, ${fmtDate(end)}` : t("unknown");
}

/** The nearest stop still served, from the analysis rows of this stop (closest first). */
export function nearestFor(analysis: Analysis | undefined, stopId: string) {
  const rows = (analysis?.stops ?? []).filter((r) => r.stopId === stopId && r.nearestServed);
  rows.sort((x, y) => (x.nearestServed!.distanceMeters ?? 1e9) - (y.nearestServed!.distanceMeters ?? 1e9));
  return rows[0]?.nearestServed ?? null;
}

/** T7-B: a phone-frame mock-up of the stop card in CityApp, filled from the real alert. No logos.
 *  S1-F: a tap on the stop asks the real stop status API. */
export function AppsView({ alert, analysis, stopId }: { closureId: string; stopId: string; alert?: Alert; analysis?: Analysis }) {
  const { t } = useTranslation();
  if (!alert) return <p className="muted">{t("unknown")}</p>;
  const near = nearestFor(analysis, stopId);
  const stopName = analysis?.stops.find((r) => r.stopId === stopId)?.name ?? stopId;
  const lines = [...new Set(alert.informedEntity.map((e) => e.routeId).filter(Boolean))].map((r) => (r as string).replace(/^R_[A-Z]+_/, ""));
  return (
    <div className="mock">
      <p className="mock-label">{t("publish.mock")}</p>
      <div className="phone" aria-label={t("publish.mock")}>
        <p className="phone-lines">
          {lines.map((l) => (
            <span key={l} className="line-chip">
              {l}
            </span>
          ))}
        </p>
        <h3>{tr(alert.headerText)}</h3>
        <p className="phone-until st-lost">{t("publish.until", { until: untilText(alert, (k) => t(k)) })}</p>
        <div className="phone-near">
          <p className="small muted">{t("publish.nearest")}</p>
          {near ? (
            near.stopId === stopId || near.distanceMeters === 0 ? (
              <p>{t("publish.servedBy")}</p>
            ) : (
              <p>
                <strong>{near.name}</strong>
                <br />
                {t("publish.walk", { dist: fmtMeters(near.distanceMeters) ?? t("unknown") })}
              </p>
            )
          ) : (
            <p>{t("publish.noNearest")}</p>
          )}
        </div>
        <StopStatusTap key={stopId} stopId={stopId} name={stopName} />
      </div>
    </div>
  );
}

/** At the stop: poster, audio (AI label), simulated LED strip, validator result. The feed links live in the „Ce primește CityApp” list (feeds.tsx). */
export function StationView({
  closureId,
  stopId,
  alert,
  validation,
}: {
  closureId: string;
  stopId: string;
  alert?: Alert;
  validation: Resource<FeedValidation>;
}) {
  const { t } = useTranslation();
  const audio = api.audioUrl(closureId, stopId);
  const [hasAudio, setHasAudio] = useState<boolean | null>(null);
  useEffect(() => {
    let live = true;
    setHasAudio(null);
    fetch(audio, { method: "HEAD" })
      .then((r) => live && setHasAudio(r.ok))
      .catch(() => live && setHasAudio(false));
    return () => {
      live = false;
    };
  }, [audio]);
  const v = validation.data;
  const lines = alert ? [...new Set(alert.informedEntity.map((e) => (e.routeId ?? "").replace(/^R_[A-Z]+_/, "")))].filter(Boolean) : [];
  return (
    <div className="station">
      <section>
        <h2>{t("publish.poster")}</h2>
        <p>
          <a href={api.posterUrl(closureId, stopId)} target="_blank" rel="noreferrer">
            {t("publish.posterOpen")}
          </a>
        </p>
      </section>
      <section>
        <h2>{t("publish.audio")}</h2>
        {hasAudio === true && (
          <>
            <audio controls preload="none" src={audio} />
            <p className="small">{t("publish.aiVoice")}</p>
          </>
        )}
        {hasAudio === false && <p className="small muted">{t("publish.noAudio")}</p>}
      </section>
      <section>
        <h2>{t("publish.ledTitle")}</h2>
        {alert && (
          <p className="led" aria-label={t("publish.led")}>
            {t("publish.ledText", { lines: lines.join(", "), until: untilText(alert, (k) => t(k)) })}
          </p>
        )}
        <p className="small muted">{t("publish.led")}</p>
      </section>
      <section>
        <h2>{t("publish.validator")}</h2>
        {v ? (
          <p>
            <span className={v.passed ? "st-ok" : "st-lost"} style={{ fontWeight: 600 }}>
              {v.passed ? t("publish.passed") : t("publish.failed")}
            </span>{" "}
            · <Figure inline value={v.errorCount} provenance={v.provenance} /> {t("publish.errors", { count: v.errorCount })} ·{" "}
            <Figure inline value={v.warningCount} provenance={v.provenance} /> {t("publish.warnings", { count: v.warningCount })}
            <br />
            <span className="small muted">{tr(v.label)}</span>
          </p>
        ) : (
          <LoadState {...validation} loading={validation.loading} />
        )}
        {v && v.rules.length > 0 && (
          <details>
            <summary>{t("details")}</summary>
            <ul className="small">
              {v.rules.map((r) => (
                <li key={r.id}>
                  {r.id} ({r.severity}): {r.title}
                  {r.note ? ` — ${tr(r.note)}` : ""}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>
    </div>
  );
}
