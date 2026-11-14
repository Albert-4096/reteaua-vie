// K1: every public output CityApp, Google and the city platform can read today, one row each.
// Only endpoints that answer 200 on the public URL are listed (D-011). Add the O2 row when it is real.
import { useTranslation } from "react-i18next";
import { apiGet } from "../../api/client";
import { tr } from "../../lib/format";
import { useResource } from "../../lib/store";
import { S } from "./strings";
import "./feeds.css";

// The example trip of the hero case: suspended line 4 stop 907 → Piața Victoriei (backend plan.demo_pair()).
const ROUTE_EXAMPLE = "/api/route?from=21.21973,45.76925&to=21.225307,45.752881";
// S1: the same hero stop 907 (Calea Torontalului, lines 2 and 4).
const STOP_EXAMPLE = "/api/stops/907/status";

const FEEDS: { name: string; href: string; where: { ro: string; en: string } }[] = [
  { name: "alerts.pb", href: "/api/feed/alerts.pb", where: S.feeds.alertsPb },
  { name: "alerts.json", href: "/api/feed/alerts.json", where: S.feeds.alertsJson },
  { name: "alerts.ngsi.json", href: "/api/feed/alerts.ngsi.json", where: S.feeds.ngsi },
  { name: "notices.json", href: "/api/feed/notices.json", where: S.feeds.notices },
  { name: "/api/route", href: ROUTE_EXAMPLE, where: S.feeds.route },
  { name: "stops/907/status", href: STOP_EXAMPLE, where: S.feeds.stopStatus },
  { name: "datex.xml", href: "/api/feed/datex.xml", where: S.feeds.datex },
];

export function FeedsView() {
  return (
    <div className="feeds">
      <h2>{tr(S.feedsTitle)}</h2>
      <p className="muted">{tr(S.feedsSentence)}</p>
      <ul className="list feeds-list">
        {FEEDS.map((f) => (
          <li key={f.name}>
            <a className="feeds-name" href={f.href} target="_blank" rel="noreferrer">
              {f.name}
            </a>
            <span>{tr(f.where)}</span>
          </li>
        ))}
        <li>
          <a className="feeds-name" href="/api/tools.json" target="_blank" rel="noreferrer">
            tools.json
          </a>
          <TimiLine />
        </li>
      </ul>
    </div>
  );
}

/** R3-F: „Pentru Timi: tools.json (N funcții, doar citire)”, N = the functions whose GET is live on this server. */
function TimiLine() {
  const { t } = useTranslation();
  const tools = useResource<{ tools: { live: boolean }[] }>("tools.json", () => apiGet("/api/tools.json"));
  const all = tools.data?.tools ?? [];
  const n = all.filter((x) => x.live).length;
  const head = tools.data
    ? tr(n === all.length ? S.timi.all : S.timi.some)
        .replace("{{n}}", String(n))
        .replace("{{total}}", String(all.length))
    : `tools.json (${tools.error ? t("unknown") : t("loading")})`;
  return (
    <span>
      {head} {tr(S.timi.where)}
    </span>
  );
}
