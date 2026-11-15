// The phone page behind a poster's QR code: /a/{closureId}?stop={stopId}.
// Without ?stop= (the link printed in the notice) it lists the stops that have their own alert.
// One look for everything a rider needs: which lines skip this stop, where to walk instead (words and map),
// and the full notice to read or to listen to. No login, no analytics: it calls only our own /api.
import { useEffect, useMemo, useRef, useState } from "react";
import type { Position } from "geojson";
import { ChevronDown, ChevronRight, Footprints, Navigation, Pause, Play, TextIcon } from "lucide-react";
import { Logo } from "@/landing/Logo";
import { MapView, type MapLabel, type MapStop } from "@/app/MapView";
import { plainName } from "@/app/lines";
import type { Alert, Analysis, AnalysisStop, ClosureSummary, Nearest, Window } from "@/app/data";
import { useApi } from "@/lib/api";
import { inkOn, useNetwork, type Network } from "@/lib/network";
import { cn } from "@/lib/utils";

type Lang = "ro" | "en";
const T = {
  ro: {
    kicker: "Transport public · Timișoara",
    closed: "Stație închisă temporar",
    skip: "Nu opresc aici",
    stillHere: "Aici opresc în continuare",
    goTo: "Mergi la cea mai apropiată stație",
    walk: (m: number, min: number) => `${m} m pe jos · ~${min} min`,
    route: "Traseu pe jos",
    listen: "Ascultă",
    pause: "Oprește",
    read: "Citește anunțul",
    hide: "Ascunde anunțul",
    ended: "Lucrarea s-a încheiat. Stația funcționează normal.",
    draft: "Previzualizare: anunțul nu este publicat încă",
    pick: "Alege stația ta",
    towards: "spre",
    from: "Din",
    untilEnd: "până la finalizarea lucrărilor",
    noAlert: "Nu există o alertă pentru această stație.",
    loading: "Se încarcă…",
    aiVoice: "Voce generată automat",
    phoneVoice: "Citit de telefon",
    source: "Sursa: anunțul STPT, publicat prin Rețeaua Vie.",
    demo: "Ora demo",
    here: "Ești aici",
    there: "Mergi aici",
    map: "Harta: stația închisă și stația unde poți urca",
  },
  en: {
    kicker: "Public transport · Timișoara",
    closed: "Stop temporarily closed",
    skip: "Not stopping here",
    stillHere: "Still stopping here",
    goTo: "Walk to the nearest stop",
    walk: (m: number, min: number) => `${m} m walk · ~${min} min`,
    route: "Walking route",
    listen: "Listen",
    pause: "Stop",
    read: "Read the notice",
    hide: "Hide the notice",
    ended: "The works are over. The stop is served as usual.",
    draft: "Preview: the notice is not published yet",
    pick: "Choose your stop",
    towards: "towards",
    from: "From",
    untilEnd: "until the works end",
    noAlert: "There is no alert for this stop.",
    loading: "Loading…",
    aiVoice: "Automatically generated voice",
    phoneVoice: "Read by your phone",
    source: "Source: STPT's notice, published through Rețeaua Vie.",
    demo: "Demo time",
    here: "You are here",
    there: "Walk here",
    map: "Map: the closed stop and the stop where you can board",
  },
};

type FullAlert = Alert & { activePeriod?: Window[]; ttsHeaderText?: { ro: string; en: string }; ttsDescriptionText?: { ro: string; en: string } };
type Near = Nearest & { location?: [number, number]; routeIds?: string[] };
type Health = { demoNow: string | null };

const enc = encodeURIComponent;
const json = <T,>(path: string) => fetch(path).then((r) => (r.ok ? (r.json() as Promise<T>) : Promise.reject(new Error(String(r.status)))));

// One poster scan per page load: a module-level guard, so StrictMode's double effect never counts twice.
// No cookie, no stored id, no retry; any error (429 too) is ignored.
let scanSent = false;
function sendScan(closureId: string, stopId: string) {
  if (scanSent) return;
  scanSent = true;
  fetch(`/api/closures/${enc(closureId)}/scans?stop=${enc(stopId)}`, { method: "POST", keepalive: true, credentials: "omit" }).catch(() => {});
}

export function StopPage() {
  const closureId = decodeURIComponent(location.pathname.split("/")[2] ?? "");
  const qs = new URLSearchParams(location.search);
  const stopId = qs.get("stop");
  const [lang, setLang] = useState<Lang>(() => (qs.get("lang") === "en" ? "en" : "ro"));
  const s = T[lang];

  const closure = useApi(() => json<ClosureSummary>(`/api/closures/${enc(closureId)}`), undefined, closureId);
  const analysis = useApi(() => json<Analysis>(`/api/closures/${enc(closureId)}/analysis`), undefined, closureId);
  const alerts = useApi(() => json<FullAlert[]>("/api/feed/alerts.json").then((all) => all.filter((a) => a.closureId === closureId)), undefined, closureId);
  const health = useApi(() => json<Health>("/api/health"));
  const net = useNetwork();

  useEffect(() => {
    document.title = "Rețeaua Vie: alertă";
    document.documentElement.lang = lang;
  }, [lang]);
  useEffect(() => {
    // preview=1: shown inside the back office. via=list: opened from this page's own stop list. Neither is a scan.
    if (stopId && !qs.has("preview") && qs.get("via") !== "list") sendScan(closureId, stopId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [closureId, stopId]);

  const c = closure.data;
  const rows = useMemo(() => (analysis.data?.stops ?? []).filter((r) => r.stopId === stopId), [analysis.data, stopId]);
  const alert = alerts.data?.find((a) => a.informedEntity.some((e) => e.stopId === stopId)) ?? null;
  const period = alert?.activePeriod?.[0] ?? c?.window;
  // Real riders scan real posters: inside the work's period the page uses the real clock. Outside it, the demo clock.
  const realNow = new Date();
  const realInside = !!period && new Date(period.start) <= realNow && realNow <= new Date(period.end);
  const demoNow = realInside ? null : (health.data?.demoNow ?? null);
  const now = demoNow ? new Date(demoNow) : realNow;
  const ended = !!period && new Date(period.end) < now;
  const openEnd = !!alert && /finalizarea lucrărilor/.test(alert.descriptionText.ro);
  const failed = !!closure.error;
  const loading = !failed && (!c || !analysis.data || !alerts.data);

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <main className="mx-auto flex max-w-md flex-col gap-4 px-4 pb-10 pt-4">
        <header className="flex items-center gap-2.5">
          <Logo className="size-7" />
          <p className="min-w-0 flex-1 truncate text-sm font-medium text-muted-foreground">{s.kicker}</p>
          <div className="flex rounded-lg bg-muted p-0.5 text-xs font-semibold" role="group" aria-label="Limba / Language">
            {(["ro", "en"] as const).map((l) => (
              <button key={l} type="button" onClick={() => setLang(l)} aria-pressed={lang === l} className={cn("h-7 rounded-md px-2.5 uppercase outline-none focus-visible:ring-2 focus-visible:ring-ring", lang === l ? "bg-card text-foreground shadow-sm" : "text-muted-foreground")}>
                {l}
              </button>
            ))}
          </div>
        </header>

        {loading && <Skeleton label={s.loading} />}
        {failed && <Card><p className="text-sm">{s.noAlert}</p></Card>}

        {!loading && c && !stopId && <StopList closureId={closureId} c={c} analysis={analysis.data!} alerts={alerts.data!} net={net} lang={lang} when={period ? when(period, lang, openEnd) : ""} />}

        {!loading && c && stopId && rows.length === 0 && !alert && <Card><p className="text-sm">{s.noAlert}</p></Card>}

        {!loading && c && stopId && (rows.length > 0 || alert) && (
          <StopView
            stopId={stopId}
            rows={rows}
            alert={alert}
            closureId={closureId}
            net={net}
            lang={lang}
            ended={ended}
            when={period ? when(period, lang, openEnd) : ""}
          />
        )}

        <footer className="mt-2 space-y-1 text-xs leading-relaxed text-muted-foreground">
          <p>{s.source}</p>
          {demoNow && <p>{s.demo}: {stamp(demoNow, lang)}</p>}
        </footer>
      </main>
    </div>
  );
}

/* ---------------- one stop ---------------- */
function StopView({ stopId, rows, alert, closureId, net, lang, ended, when }: { stopId: string; rows: AnalysisStop[]; alert: FullAlert | null; closureId: string; net: Network | null; lang: Lang; ended: boolean; when: string }) {
  const s = T[lang];
  const [reading, setReading] = useState(false);
  const fromAlert = alert ? (alert.headerText.ro.match(/^Stația (.+?) nu este/)?.[1] ?? null) : null;
  const full = rows[0]?.name ?? fromAlert ?? stopId;
  const name = plainName(full);
  const where = full.match(/\(([^)]*)\)\s*$/)?.[1]?.replace(/ - /g, " – ");
  const headsign = rows[0]?.headsign;
  const skipped = uniq(alert ? alert.informedEntity.filter((e) => e.stopId === stopId && e.routeId).map((e) => e.routeId!) : rows.filter((r) => r.state !== "served").map((r) => r.routeId));
  const near = nearestFor(rows);
  const stillServed = !!near && (near.stopId === stopId || near.distanceMeters === 0);
  const here = rows[0]?.location ?? netStop(net, stopId);
  const there = near?.location ?? (near ? netStop(net, near.stopId) : null);
  const meters = near ? Math.round(near.distanceMeters / 10) * 10 : 0;
  const minutes = Math.max(1, Math.ceil(near ? near.distanceMeters / 80 : 0)); // 80 m a minute, an unhurried walk

  const speech = alert
    ? [alert.ttsHeaderText?.[lang] ?? alert.headerText[lang], alert.ttsDescriptionText?.[lang] ?? alert.descriptionText[lang]].join(" ")
    : [`${s.closed}: ${name}.`, near && !stillServed ? `${s.goTo}: ${plainName(near.name)}, ${meters} m.` : ""].join(" ");

  return (
    <>
      <Card className="space-y-3">
        <div className="flex flex-wrap gap-1.5">
          {ended ? <Pill tone="green">{s.ended}</Pill> : <Pill tone="closure">{s.closed}</Pill>}
          {!alert && <Pill tone="neutral">{s.draft}</Pill>}
        </div>
        <div>
          <h1 className="text-[1.75rem] font-semibold leading-[1.1] tracking-tight">{name}</h1>
          {(where || headsign) && (
            <p className="mt-1 text-sm text-muted-foreground">
              {where}
              {where && headsign && " · "}
              {headsign && `${s.towards} ${headsign}`}
            </p>
          )}
        </div>
        {skipped.length > 0 && !ended && (
          <div>
            <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">{s.skip}</p>
            <Chips ids={skipped} net={net} struck />
          </div>
        )}
        {when && <p className="text-sm font-medium">{when}</p>}
      </Card>

      {!ended && near && (
        <Card className="overflow-hidden p-0">
          {here && (
            <div className="relative h-56 border-b bg-muted" role="img" aria-label={s.map}>
              <MiniMap here={here} there={stillServed ? null : there} routeIds={skipped} lang={lang} />
            </div>
          )}
          <div className="space-y-3 p-4">
            {stillServed ? (
              <>
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{s.stillHere}</p>
                <Chips ids={near.routeIds ?? []} net={net} />
              </>
            ) : (
              <>
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{s.goTo}</p>
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-full bg-accent text-accent-foreground"><Footprints className="size-4.5" strokeWidth={2} /></span>
                  <div className="min-w-0">
                    <p className="text-lg font-semibold leading-snug">{plainName(near.name)}</p>
                    <p className="text-sm text-muted-foreground">{[near.name.match(/\(([^)]*)\)\s*$/)?.[1], s.walk(meters, minutes)].filter(Boolean).join(" · ")}</p>
                  </div>
                </div>
                {!!near.routeIds?.length && <Chips ids={near.routeIds} net={net} />}
                {here && there && (
                  <a
                    href={`https://www.google.com/maps/dir/?api=1&origin=${here[1]},${here[0]}&destination=${there[1]},${there[0]}&travelmode=walking`}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex h-10 items-center gap-2 rounded-lg border px-3.5 text-sm font-medium outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <Navigation className="size-4" /> {s.route}
                  </a>
                )}
              </>
            )}
          </div>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-2">
        <Listen closureId={closureId} stopId={stopId} hasAlert={!!alert} speech={speech} lang={lang} />
        <button
          type="button"
          onClick={() => setReading((x) => !x)}
          aria-expanded={reading}
          className="inline-flex h-12 items-center justify-center gap-2 rounded-xl border bg-card text-sm font-semibold shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {reading ? <ChevronDown className="size-4" /> : <TextIcon className="size-4" />} {reading ? s.hide : s.read}
        </button>
      </div>
      {reading && (
        <Card>
          <p className="whitespace-pre-line text-[0.95rem] leading-relaxed">{alert ? alert.descriptionText[lang] : speech}</p>
        </Card>
      )}
    </>
  );
}

/* ---------------- no stop in the address: the stops that have their own alert ---------------- */
function StopList({ closureId, c, analysis, alerts, net, lang, when }: { closureId: string; c: ClosureSummary; analysis: Analysis; alerts: FullAlert[]; net: Network | null; lang: Lang; when: string }) {
  const s = T[lang];
  const ids = uniq(alerts.flatMap((a) => a.informedEntity.map((e) => e.stopId).filter((x): x is string => !!x)));
  const stops = ids
    .map((id) => {
      const r = analysis.stops.find((x) => x.stopId === id);
      const header = alerts.find((a) => a.informedEntity.some((e) => e.stopId === id))?.headerText.ro ?? "";
      return { id, name: r?.name ?? header.match(/^Stația (.+?) nu este/)?.[1] ?? id, towards: r?.headsign ?? null, routes: uniq(alerts.filter((a) => a.informedEntity.some((e) => e.stopId === id)).flatMap((a) => a.informedEntity.filter((e) => e.stopId === id && e.routeId).map((e) => e.routeId!))) };
    })
    .sort((a, b) => a.name.localeCompare(b.name, "ro") || a.id.localeCompare(b.id));
  return (
    <>
      <Card className="space-y-2">
        <h1 className="text-2xl font-semibold leading-tight tracking-tight">{c.title[lang]}</h1>
        {when && <p className="text-sm font-medium">{when}</p>}
      </Card>
      {stops.length === 0 ? (
        <Card><p className="text-sm">{s.draft}</p></Card>
      ) : (
        <Card className="p-0">
          <p className="px-4 pb-1 pt-4 text-xs font-medium uppercase tracking-wide text-muted-foreground">{s.pick}</p>
          <ul className="divide-y">
            {stops.map((st) => (
              <li key={st.id}>
                <a href={`/a/${enc(closureId)}?stop=${enc(st.id)}&via=list${lang === "en" ? "&lang=en" : ""}`} className="flex items-center gap-3 px-4 py-3 outline-none hover:bg-muted focus-visible:bg-muted">
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium leading-snug">{plainName(st.name)}</span>
                    {st.towards && <span className="block text-xs text-muted-foreground">{s.towards} {st.towards}</span>}
                  </span>
                  <Chips ids={st.routes.slice(0, 3)} net={net} small />
                  <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                </a>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}

/* ---------------- pieces ---------------- */
function MiniMap({ here, there, routeIds, lang }: { here: [number, number]; there: [number, number] | null; routeIds: string[]; lang: Lang }) {
  const s = T[lang];
  const stops: MapStop[] = [{ id: "here", name: s.here, lon: here[0], lat: here[1], tone: "closed" }];
  const labels: MapLabel[] = [{ id: "here", lon: here[0], lat: here[1], text: s.here, tone: "work", place: there && there[1] > here[1] ? "bottom" : "top" }];
  const points: Position[] = [here];
  if (there) {
    stops.push({ id: "there", name: s.there, lon: there[0], lat: there[1], tone: "served" });
    labels.push({ id: "there", lon: there[0], lat: there[1], text: s.there, tone: "stop", place: there[1] > here[1] ? "top" : "bottom" });
    points.push(there);
  }
  return (
    <MapView
      still
      highlight={routeIds}
      stops={stops}
      labels={labels}
      detour={there ? [here, there] : null}
      fit={{ key: `${here.join()}|${there?.join() ?? ""}`, points, maxZoom: 16.2, padding: 44 }}
    />
  );
}

function Chips({ ids, net, struck, small }: { ids: string[]; net: Network | null; struck?: boolean; small?: boolean }) {
  return (
    <span className="flex flex-wrap gap-1.5">
      {ids.map((id) => {
        const r = net?.byId.get(id);
        const color = r ? `#${r.color}` : "var(--muted)";
        return (
          <span
            key={id}
            className={cn("inline-flex items-center justify-center rounded-md font-semibold tabular-nums", small ? "h-6 min-w-7 px-1.5 text-xs" : "h-8 min-w-10 px-2.5 text-sm", struck && "line-through decoration-2")}
            style={{ background: color, color: r ? inkOn(r.color) : "var(--foreground)" }}
          >
            {r?.shortName ?? shortName(id)}
          </span>
        );
      })}
    </span>
  );
}

/** MP3 made at publish; if there is none, the phone reads the text (Web Speech). */
function Listen({ closureId, stopId, hasAlert, speech, lang }: { closureId: string; stopId: string; hasAlert: boolean; speech: string; lang: Lang }) {
  const s = T[lang];
  const url = `/api/closures/${enc(closureId)}/audio/${enc(stopId)}.mp3`;
  const [mp3, setMp3] = useState<boolean | null>(hasAlert && lang === "ro" ? null : false);
  const [playing, setPlaying] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);
  const canSpeak = typeof window !== "undefined" && "speechSynthesis" in window;

  useEffect(() => {
    let live = true;
    if (hasAlert && lang === "ro") fetch(url, { method: "HEAD" }).then((r) => live && setMp3(r.ok)).catch(() => live && setMp3(false));
    else setMp3(false);
    return () => {
      live = false;
      audio.current?.pause();
      audio.current = null;
      if (canSpeak) window.speechSynthesis.cancel();
      setPlaying(false);
    };
  }, [url, hasAlert, lang, canSpeak]);

  function speak() {
    const u = new SpeechSynthesisUtterance(speech);
    u.lang = lang === "ro" ? "ro-RO" : "en-GB";
    const v = window.speechSynthesis.getVoices().find((x) => x.lang.toLowerCase().startsWith(lang));
    if (v) u.voice = v;
    u.onend = u.onerror = () => setPlaying(false);
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
      audio.current ??= Object.assign(new Audio(url), { onended: () => setPlaying(false) });
      audio.current.currentTime = 0;
      audio.current.play().then(() => setPlaying(true)).catch(() => (canSpeak ? speak() : setPlaying(false)));
      return;
    }
    if (canSpeak) speak();
  }

  if (mp3 === false && !canSpeak) return <span />;
  return (
    <button
      type="button"
      onClick={toggle}
      disabled={mp3 === null}
      aria-pressed={playing}
      title={mp3 ? s.aiVoice : s.phoneVoice}
      className="inline-flex h-12 items-center justify-center gap-2 rounded-xl bg-primary text-sm font-semibold text-primary-foreground shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-60"
    >
      {playing ? <Pause className="size-4" fill="currentColor" /> : <Play className="size-4" fill="currentColor" />} {playing ? s.pause : s.listen}
    </button>
  );
}

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <section className={cn("rounded-2xl border bg-card p-4 shadow-[var(--shadow-card)]", className)}>{children}</section>;
}

function Pill({ tone, children }: { tone: "closure" | "green" | "neutral"; children: React.ReactNode }) {
  const cls = { closure: "bg-closure-soft text-closure-ink", green: "bg-accent text-accent-foreground", neutral: "bg-muted text-muted-foreground" }[tone];
  return (
    <span className={cn("inline-flex min-h-7 items-center gap-1.5 rounded-full px-2.5 text-xs font-semibold", cls)}>
      {tone === "closure" && <span className="size-1.5 rounded-full bg-closure" aria-hidden />}
      {children}
    </span>
  );
}

function Skeleton({ label }: { label: string }) {
  return (
    <div className="space-y-3" aria-busy="true" aria-label={label}>
      <div className="h-40 animate-pulse rounded-2xl bg-muted" />
      <div className="h-64 animate-pulse rounded-2xl bg-muted" />
    </div>
  );
}

/* ---------------- helpers ---------------- */
const uniq = <T,>(xs: T[]) => [...new Set(xs)];
const shortName = (routeId: string) => routeId.replace(/^R_[A-Z]+_/, "").replace(/(\d)([A-Z])$/, (_, d: string, l: string) => d + l.toLowerCase());

function nearestFor(rows: AnalysisStop[]): Near | null {
  const withNear = rows.filter((r) => r.nearestServed).map((r) => r.nearestServed as Near);
  withNear.sort((a, b) => (a.distanceMeters ?? 1e9) - (b.distanceMeters ?? 1e9));
  return withNear[0] ?? null;
}

function netStop(net: Network | null, id: string): [number, number] | null {
  const x = net?.stops.find((st) => st.id === id);
  return x ? [x.lon, x.lat] : null;
}

const TZ = "Europe/Bucharest";
function parts(iso: string, lang: Lang) {
  const d = new Date(iso);
  const day = new Intl.DateTimeFormat(lang === "ro" ? "ro-RO" : "en-GB", { day: "numeric", month: "short", timeZone: TZ }).format(d);
  const time = new Intl.DateTimeFormat("ro-RO", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: TZ }).format(d);
  return { day, time };
}
const stamp = (iso: string, lang: Lang) => { const p = parts(iso, lang); return `${p.day}, ${p.time}`; };

/** A period as the notice writes it: an end at midnight is 24:00 of the day before. */
function when(w: Window, lang: Lang, openEnd: boolean): string {
  const s = T[lang];
  const a = stamp(w.start, lang);
  if (openEnd) return `${s.from} ${a}, ${s.untilEnd}`;
  const e = parts(w.end, lang);
  const b = e.time === "00:00" ? `${parts(new Date(new Date(w.end).getTime() - 60_000).toISOString(), lang).day}, 24:00` : `${e.day}, ${e.time}`;
  const sameDay = b.startsWith(`${parts(w.start, lang).day},`);
  return sameDay ? `${a}–${b.slice(b.indexOf(",") + 2)}` : `${a} – ${b}`;
}
