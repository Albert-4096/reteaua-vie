// N3: the state of the data in one row of the top bar. A click opens the sources (a popover, not a screen).
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type Health } from "../api/client";
import { fmtDateTime } from "../lib/format";
import { load, useResource } from "../lib/store";

const POLL_MS = 60_000;

/** Optional per-source freshness (N3-B). Read only when the backend sends it. */
type Source = { id: string; lastOkAt?: string | null; version?: string | null; stale?: boolean | null };
type HealthWithSources = Health & { sources?: Source[] | null };

const fetchHealth = () => api.health();

/** „app.m6_parking.api_parking” → the module's plain name; unknown paths stay as they are. */
function moduleName(path: string, names: Record<string, string>): string {
  const m = /\.(m\d)_/.exec(path);
  if (m && names[m[1]]) return names[m[1]];
  const part = path.split(".")[1];
  return (part && names[part]) || path;
}

function minutesSince(iso: string, now: number): number {
  return Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000));
}

export function DataStatus() {
  const { t } = useTranslation();
  const health = useResource<HealthWithSources>("health", fetchHealth);
  const [checkedAt, setCheckedAt] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => {
      load("health", fetchHealth, true);
      setCheckedAt(Date.now());
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, []);

  const h = health.data;
  const names = t("data.modules", { returnObjects: true }) as Record<string, string>;
  const failed = (h?.modulesFailed ?? []).map((p) => moduleName(p, names));
  const stale = (h?.sources ?? []).filter((s) => s.stale);
  const down = !!health.error && !h;

  const summary = down
    ? t("data.serverDown")
    : !h
      ? t("loading")
      : h.feedVersion
        ? t("data.gtfs", { v: h.feedVersion })
        : t("data.gtfsUnknown");
  const fetched = h?.dataFetchedAt ? ` · ${t("data.fetched", { at: fmtDateTime(h.dataFetchedAt) })}` : "";

  const warnings = [
    ...failed.map((n) => t("data.failed", { name: n })),
    ...stale.map((s) =>
      s.lastOkAt
        ? t("data.staleAgo", { name: names[s.id] ?? s.id, min: minutesSince(s.lastOkAt, checkedAt) })
        : t("data.stale", { name: names[s.id] ?? s.id }),
    ),
  ];

  return (
    <>
      <button
        type="button"
        className="data-status"
        popoverTarget="data-status-pop"
        aria-label={t("data.open")}
        data-state={down ? "down" : warnings.length ? "warn" : "ok"}
      >
        <span>
          {summary}
          {fetched && <span className="data-status-date">{fetched}</span>}
        </span>
        {warnings.length > 0 && <span className="data-status-warn">{warnings.join(" · ")}</span>}
      </button>
      <div id="data-status-pop" popover="auto" className="data-status-pop" role="dialog" aria-label={t("data.title")}>
        <h2>{t("data.title")}</h2>
        {down && <p className="data-status-down">{t("data.serverDownBody")}</p>}
        {h && (
          <dl>
            <dt>{t("data.gtfsLabel")}</dt>
            <dd>{h.feedVersion ?? t("unknown")}</dd>
            <dt>{t("data.fetchedLabel")}</dt>
            <dd>{h.dataFetchedAt ? fmtDateTime(h.dataFetchedAt) : t("unknown")}</dd>
            {h.dataFrozenAt && (
              <>
                <dt>{t("data.frozenLabel")}</dt>
                <dd>{fmtDateTime(h.dataFrozenAt)}</dd>
              </>
            )}
            {(h.sources ?? []).map((s) => (
              <SourceRow key={s.id} s={s} name={names[s.id] ?? s.id} now={checkedAt} />
            ))}
            <dt>{t("data.modulesLabel")}</dt>
            <dd className={failed.length ? "data-status-bad" : undefined}>
              {failed.length ? t("data.failedList", { list: failed.join(", ") }) : t("data.allOk")}
            </dd>
          </dl>
        )}
        <p className="data-status-foot">{t("data.checked", { at: fmtDateTime(new Date(checkedAt).toISOString()) })}</p>
      </div>
    </>
  );
}

function SourceRow({ s, name, now }: { s: Source; name: string; now: number }) {
  const { t } = useTranslation();
  const when = s.lastOkAt ? fmtDateTime(s.lastOkAt) : t("unknown");
  return (
    <>
      <dt>{name}</dt>
      <dd className={s.stale ? "data-status-bad" : undefined}>
        {s.version ? `${s.version} · ` : ""}
        {s.stale
          ? s.lastOkAt
            ? t("data.staleRow", { min: minutesSince(s.lastOkAt, now) })
            : t("data.staleRowUnknown")
          : when}
      </dd>
    </>
  );
}
