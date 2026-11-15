// Public page behind the poster's QR code: /a/{closureId}?stop={stopId} (SPEC §7.2, T8).
// Without ?stop= (the link printed in the notice) it lists the stops that have an alert, each with its own page.
// Mobile first, no login, no analytics: it calls only our own /api.
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type Alert, type Analysis, type Closure, type Health } from "../api/client";
import { fmtDate, fmtDateTime, fmtMeters, fmtTime, fmtWindow } from "../lib/format";
import { useResource } from "../lib/store";
import { nearestFor } from "../steps/3-publish/outputs";

type Props = { closureId: string; stopId: string | null };

// One poster scan per page load (R7): a module-level guard, so React StrictMode's double effect
// or a re-render never counts twice. No cookie, no stored id, no retry; any error (429 too) is ignored.
let scanSent = false;
function sendScan(closureId: string, stopId: string) {
  if (scanSent) return;
  scanSent = true;
  fetch(`/api/closures/${encodeURIComponent(closureId)}/scans?stop=${encodeURIComponent(stopId)}`, {
    method: "POST",
    keepalive: true,
    credentials: "omit",
  }).catch(() => {});
}

export function QrPage({ closureId, stopId }: Props) {
  const { t } = useTranslation();
  const health = useResource<Health>("health", () => api.health());
  const closure = useResource<Closure>(`closure:${closureId}`, () => api.closure(closureId));
  const alerts = useResource<Alert[]>(`alerts:${closureId}`, () =>
    api.alerts().then((all) => all.filter((a) => a.closureId === closureId)),
  );
  const analysis = useResource<Analysis>(`analysis:${closureId}`, () => api.analysis(closureId));

  useEffect(() => {
    document.title = "Rețeaua Vie: alertă";
  }, []);

  useEffect(() => {
    // preview=1: the phone frame in step 3 of the back office. via=list: opened from this page's own stop list.
    // Neither is a poster scan.
    const q = new URLSearchParams(window.location.search);
    if (stopId && !q.has("preview") && q.get("via") !== "list") sendScan(closureId, stopId);
  }, [closureId, stopId]);

  const c = closure.data;
  const alert =
    (stopId && alerts.data?.find((a) => a.informedEntity.some((e) => e.stopId === stopId))) ||
    (!stopId ? alerts.data?.find((a) => a.informedEntity.every((e) => !e.stopId)) : undefined);
  const loading = closure.loading || alerts.loading || health.loading;
  const period = alert?.activePeriod[0] ?? c?.window;
  // Real residents scan real posters: inside the closure window the page uses the real clock and
  // shows no simulation text. Only outside it does it fall back to the demo clock (labelled „Simulare”).
  const realNow = new Date();
  const realInside = !!period && new Date(period.start) <= realNow && realNow <= new Date(period.end);
  const demoNow = realInside ? null : (health.data?.demoNow ?? null);
  const now = demoNow ? new Date(demoNow) : realNow;
  const ended = !!period && new Date(period.end) < now;
  const openEnd = !!alert && /finalizarea lucrărilor/.test(alert.descriptionText.ro);
  const near = stopId ? nearestFor(analysis.data, stopId) : null;
  const stopList = !stopId && !alert ? stopsWithAlert(alerts.data ?? [], analysis.data) : [];

  return (
    <main className="qr" lang="ro">
      <p className="qr-kicker">{t("qr.kicker")}</p>
      {loading && !c && <p className="state-msg">{t("loading")}</p>}
      {closure.error && <p className="error-msg">{t("qr.noAlert")}</p>}
      {c && !alert && !alerts.loading && stopList.length > 0 && (
        <>
          <h1>{c.title.ro}</h1>
          <dl className="qr-facts">
            <div>
              <dt>{t("qr.window")}</dt>
              <dd>{fmtPeriod(c.window)}</dd>
            </div>
          </dl>
          <section aria-labelledby="qr-stops-title">
            <h2 id="qr-stops-title">{t("qr.pickStop")}</h2>
            <ul className="qr-stops">
              {stopList.map((s) => (
                <li key={s.stopId}>
                  <a href={`/a/${encodeURIComponent(closureId)}?stop=${encodeURIComponent(s.stopId)}&via=list`}>
                    <span className="qr-stop-name">{s.name}</span>
                    {s.towards && <span className="small muted">{t("qr.towards", { headsign: s.towards })}</span>}
                  </a>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
      {c && !alert && !alerts.loading && stopList.length === 0 && (
        <>
          <h1>{c.title.ro}</h1>
          <p className="qr-status">{t(stopId ? "qr.noAlert" : "qr.notPublished")}</p>
        </>
      )}
      {c && alert && (
        <>
          {ended && <p className="qr-ended">{t("qr.inactive")}</p>}
          <h1>{alert.headerText.ro}</h1>

          <dl className="qr-facts">
            <div>
              <dt>{t("qr.window")}</dt>
              <dd>
                {period && openEnd
                  ? `${t("qr.from")} ${fmtDateTime(period.start)}, ${t("qr.untilEnd")}`
                  : period && fmtPeriod(period)}
              </dd>
            </div>
            {stopId && (
              <div>
                <dt>{t("qr.nearest")}</dt>
                <dd>
                  {near
                    ? near.stopId === stopId || near.distanceMeters === 0
                      ? t("qr.stillServed", { lines: shortNames(near.routeIds) })
                      : `${near.name}, ${t("qr.walk", { dist: fmtMeters(near.distanceMeters) ?? t("unknown") })}`
                    : t("unknown")}
                </dd>
              </div>
            )}
          </dl>

          {!ended && stopId && <Listen closureId={closureId} stopId={stopId} alert={alert} />}

          <p className="qr-text">{alert.descriptionText.ro}</p>

          {alert.headerText.en && (
            <section lang="en" className="qr-en">
              <h2>{alert.headerText.en}</h2>
              {alert.descriptionText.en && <p className="qr-text">{alert.descriptionText.en}</p>}
            </section>
          )}
        </>
      )}
      <footer className="qr-foot">
        {demoNow && <p>{t("clock", { time: fmtDateTime(demoNow) })}</p>}
        <p>{t("qr.source")}</p>
      </footer>
    </main>
  );
}

/** A period as the alert text writes it: an end at midnight is 24:00 of the day before, so the two never disagree on one screen. */
function fmtPeriod(w: { start: string; end: string }): string {
  if (fmtTime(w.end) !== "00:00") return fmtWindow(w);
  const dayBefore = new Date(new Date(w.end).getTime() - 60_000).toISOString();
  return fmtDate(w.start) === fmtDate(dayBefore)
    ? `${fmtDate(w.start)}, ${fmtTime(w.start)}–24:00`
    : `${fmtDate(w.start)}, ${fmtTime(w.start)} – ${fmtDate(dayBefore)}, 24:00`;
}

/** The stops that have their own alert, by name; two stops with one name also say where the vehicle goes. */
function stopsWithAlert(alerts: Alert[], analysis: Analysis | null | undefined) {
  const ids = [...new Set(alerts.flatMap((a) => a.informedEntity.map((e) => e.stopId).filter((s): s is string => !!s)))];
  const rows = ids.map((id) => {
    const s = analysis?.stops.find((x) => x.stopId === id);
    const header = alerts.find((a) => a.informedEntity.some((e) => e.stopId === id))?.headerText.ro ?? "";
    return { stopId: id, name: s?.name ?? header.match(/^Stația (.+?) nu este/)?.[1] ?? id, towards: s?.headsign ?? null };
  });
  const shared = (name: string) => rows.filter((r) => r.name === name).length > 1;
  return rows
    .sort((a, b) => a.name.localeCompare(b.name, "ro") || a.stopId.localeCompare(b.stopId))
    .map((r) => ({ ...r, towards: shared(r.name) ? r.towards : null }));
}

function shortNames(routeIds: string[] | null | undefined): string {
  return [...new Set((routeIds ?? []).map((r) => r.replace(/^R_[A-Z]+_/, "")))].join(", ");
}

/** MP3 made at publish; if there is none, the phone reads the alert text (Web Speech, ro-RO). */
function Listen({ closureId, stopId, alert }: { closureId: string; stopId: string; alert: Alert }) {
  const { t } = useTranslation();
  const url = api.audioUrl(closureId, stopId);
  const [mp3, setMp3] = useState<boolean | null>(null);
  const [playing, setPlaying] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);
  const canSpeak = typeof window !== "undefined" && "speechSynthesis" in window;

  useEffect(() => {
    let live = true;
    fetch(url, { method: "HEAD" })
      .then((r) => live && setMp3(r.ok))
      .catch(() => live && setMp3(false));
    return () => {
      live = false;
      audio.current?.pause();
      if (canSpeak) window.speechSynthesis.cancel();
    };
  }, [url, canSpeak]);

  function speak() {
    const text = [alert.ttsHeaderText?.ro ?? alert.headerText.ro, alert.ttsDescriptionText?.ro ?? alert.descriptionText.ro].join(" ");
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "ro-RO";
    const ro = window.speechSynthesis.getVoices().find((v) => v.lang.toLowerCase().startsWith("ro"));
    if (ro) u.voice = ro;
    u.onend = () => setPlaying(false);
    u.onerror = () => setPlaying(false);
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
    setPlaying(true);
  }

  function toggle() {
    if (playing) {
      audio.current?.pause();
      if (canSpeak) window.speechSynthesis.cancel();
      setPlaying(false);
      return;
    }
    if (mp3) {
      if (!audio.current) {
        audio.current = new Audio(url);
        audio.current.onended = () => setPlaying(false);
      }
      audio.current.currentTime = 0;
      audio.current
        .play()
        .then(() => setPlaying(true))
        .catch(() => (canSpeak ? speak() : setPlaying(false)));
      return;
    }
    if (canSpeak) speak();
  }

  if (mp3 === false && !canSpeak) return <p className="small muted">{t("qr.noSpeech")}</p>;
  return (
    <div className="qr-listen">
      <button type="button" className="btn btn-primary qr-listen-btn" disabled={mp3 === null} onClick={toggle} aria-pressed={playing}>
        {playing ? t("qr.stop") : t("qr.listen")}
      </button>
      <p className="small">{mp3 === false ? t("qr.speechFallback") : t("qr.aiVoice")}</p>
    </div>
  );
}
