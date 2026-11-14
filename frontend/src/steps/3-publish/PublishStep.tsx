// Step 3 Publici: one button, then what people would receive: the notice (D-013), in apps (mock-up), at the stop.
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  api,
  ApiError,
  type Alert,
  type Analysis,
  type Closure,
  type ClosureSummary,
  type FeedValidation,
  type GeneratedNotice,
  type Provenance,
  type PublishResult,
} from "../../api/client";
import { CasePicker } from "../../components/CasePicker";
import { Figure } from "../../components/Figure";
import { useMapOverlay } from "../../components/MapView";
import { LoadState, Panel } from "../../components/Panel";
import { undecidedCount } from "../../lib/decisions";
import { errorText } from "../../lib/errors";
import { fmtDateTime, tr } from "../../lib/format";
import { navigate, stepHref } from "../../lib/router";
import { invalidate, setData, useResource } from "../../lib/store";
import type { StepProps } from "../types";
import { CityAppCheck } from "./CityAppCheck";
import { JournalFold } from "./JournalFold";
import { FeedCheckRow } from "./feedCheck";
import { FeedsView } from "./feeds";
import { AppsView, NoticeView, StationView } from "./outputs";
import { PhoneFrame } from "./QrMoment";
import { S } from "./strings";

type Out = "notice" | "apps" | "station" | "feeds";

export function PublishStep(props: StepProps) {
  if (!props.closureId) return <CasePicker step={3} />;
  return <Publish {...props} closureId={props.closureId} />;
}

function Publish({ closureId, caseKey }: StepProps & { closureId: string }) {
  const { t } = useTranslation();
  const closure = useResource<Closure>(`closure:${closureId}`, () => api.closure(closureId));
  const analysis = useResource<Analysis>(`analysis:${closureId}`, () => api.analysis(closureId));
  const notice = useResource<GeneratedNotice>(`notice:${closureId}`, () => api.notice(closureId));
  const published = closure.data?.status === "published";
  const alerts = useResource<Alert[]>(published ? `alerts:${closureId}` : null, () =>
    api.alerts().then((all) => all.filter((a) => a.closureId === closureId)),
  );
  const validation = useResource<FeedValidation>(published ? `validation:${closureId}` : null, () => api.validation(closureId));
  const summaries = useResource<ClosureSummary[]>("closures", () => api.closures());
  const [result, setResult] = useState<PublishResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [out, setOut] = useState<Out>("notice");
  const [stopId, setStopId] = useState<string | null>(null);
  const [phone, setPhone] = useState(false);

  const c = closure.data;
  useMapOverlay({ closure: (c?.geometry as GeoJSON.Geometry | null) ?? null, fitKey: c ? closureId : undefined }, [c, closureId]);

  const stopAlerts = useMemo(
    () => (alerts.data ?? []).filter((a) => a.informedEntity.some((e) => e.stopId) && a.id.includes("_stop_")),
    [alerts.data],
  );
  const noService = new Set((notice.data?.stopsWithNoService ?? []).map((s) => s.stopId));
  const defaultStop =
    stopAlerts.find((a) => a.informedEntity.some((e) => e.stopId && noService.has(e.stopId)))?.informedEntity[0].stopId ??
    stopAlerts[0]?.informedEntity[0].stopId ??
    null;
  const selected = stopId ?? defaultStop;

  if (closure.error || !c) {
    return (
      <Panel title={t("publish.title")}>
        <LoadState loading error={closure.error} />
      </Panel>
    );
  }

  const left = analysis.data ? undecidedCount(analysis.data) : 0;

  async function publish() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.publish(closureId);
      setResult(res);
      setData(`alerts:${closureId}`, res.alerts);
      setOut("station"); // straight to the poster and its QR: the next thing shown after Publish (D-028)
      invalidate(`closure:${closureId}`, `notice:${closureId}`, `validation:${closureId}`, "closures", "linesStatus", "lineStatusRow:", "stopStatus:");
    } catch (e) {
      setError(e instanceof ApiError && e.code === "UNCONFIRMED" ? t("publish.blocked", { count: left }) : errorText(e, t));
    } finally {
      setBusy(false);
    }
  }

  const publishedAt = result?.publishedAt ?? summaries.data?.find((x) => x.id === closureId)?.publishedAt ?? null;
  const outProv: Provenance[] = [
    { source: "Rețeaua Vie: alerta publicată (GTFS-RT)", url: "/api/feed/alerts.json", version: null, fetchedAt: publishedAt ?? "", note: null },
  ];
  const outs: { id: Out; label: string }[] = [
    { id: "notice", label: t("publish.outNotice") },
    { id: "apps", label: t("publish.outApps") },
    { id: "station", label: t("publish.outStation") },
    { id: "feeds", label: tr(S.feedsTab) },
  ];
  const qrHref = selected ? `/a/${encodeURIComponent(closureId)}?stop=${encodeURIComponent(selected)}` : null;

  return (
    <>
      <section className="stage" aria-label={outs.find((o) => o.id === out)?.label}>
        {out === "notice" && (notice.data ? <NoticeView notice={notice.data} /> : <LoadState {...notice} loading />)}
        {out === "feeds" && <FeedsView />}
        {(out === "apps" || out === "station") && !published && <p className="state-msg">{t("publish.notPublished")}</p>}
        {(out === "apps" || out === "station") && published && (
          <>
            <StopPicker alerts={stopAlerts} value={selected} onChange={setStopId} />
            {selected && out === "apps" && (
              <AppsView closureId={closureId} stopId={selected} alert={findAlert(stopAlerts, selected)} analysis={analysis.data} />
            )}
            {selected && out === "station" && (
              <StationView closureId={closureId} stopId={selected} alert={findAlert(stopAlerts, selected)} validation={validation} />
            )}
          </>
        )}
      </section>
      <Panel
        title={t("publish.title")}
        sentence={
          published
            ? publishedAt
              ? t("publish.sentenceAfter", { time: fmtDateTime(publishedAt) })
              : t("publish.sentenceAfterNoTime")
            : t("publish.sentenceBefore")
        }
        foot={
          published ? (
            qrHref && (
              <>
                <button type="button" className="btn btn-primary" onClick={() => setPhone(true)}>
                  {tr(S.qrPhoneOpen)}
                </button>
                <PhoneFrame href={qrHref} open={phone} onClose={() => setPhone(false)} />
              </>
            )
          ) : (
            <>
              <button type="button" className="btn btn-primary" disabled={busy || left > 0} onClick={() => void publish()}>
                {busy ? t("publish.publishing") : t("publish.button")}
              </button>
              {left > 0 && (
                <p className="hint">
                  {t("publish.blocked", { count: left })}{" "}
                  <a
                    href={stepHref(1, caseKey)}
                    onClick={(e) => {
                      e.preventDefault();
                      navigate(stepHref(1, caseKey));
                    }}
                  >
                    {t("steps.1")}
                  </a>
                </p>
              )}
            </>
          )
        }
      >
        {published && alerts.data && (
          <div className="figures">
            <Figure value={alerts.data.length} label={t("publish.figAlerts")} provenance={outProv} />
            <Figure value={stopAlerts.length} label={t("publish.figPosters")} provenance={outProv} />
          </div>
        )}
        {published && <CityAppCheck closureId={closureId} />}
        {published && <FeedCheckRow closureId={closureId} />}
        <nav aria-label={t("publish.outputs")}>
          <ul className="list">
            {outs.map((o) => (
              <li key={o.id}>
                <button type="button" className="row-button" aria-current={out === o.id ? "true" : undefined} onClick={() => setOut(o.id)}>
                  <span style={{ fontWeight: out === o.id ? 600 : 400 }}>{o.label}</span>
                  <span aria-hidden="true" className="muted" style={{ marginLeft: "auto" }}>
                    {out === o.id ? "●" : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </nav>
        {error && <p className="error-msg">{error}</p>}
        <JournalFold closureId={closureId} />
        <p className="small muted">{tr(c.title)}</p>
      </Panel>
    </>
  );
}

function findAlert(alerts: Alert[], stopId: string): Alert | undefined {
  return alerts.find((a) => a.informedEntity.some((e) => e.stopId === stopId));
}

function StopPicker({ alerts, value, onChange }: { alerts: Alert[]; value: string | null; onChange: (s: string) => void }) {
  const { t } = useTranslation();
  const options = alerts.map((a) => ({ id: a.informedEntity[0].stopId as string, name: stopNameOf(a) }));
  return (
    <p className="stage-picker">
      <label>
        {t("publish.stop")}:{" "}
        <select value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
          {options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name} ({o.id})
            </option>
          ))}
        </select>
      </label>
    </p>
  );
}

/** „Stația X nu este deservită…” → X. Falls back to the header when the template differs. */
export function stopNameOf(a: Alert): string {
  const h = a.headerText.ro;
  const m = h.match(/^Stația (.+?) nu (este|mai)/);
  return m ? m[1] : h;
}
