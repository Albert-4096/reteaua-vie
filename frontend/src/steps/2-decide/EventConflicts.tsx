// N2: recorded city events near the closure; long exhibitions are not presented as day events.
import { useTranslation } from "react-i18next";
import { apiGet, type I18n, type Provenance } from "../../api/client";
import { Figure } from "../../components/Figure";
import { LoadState } from "../../components/Panel";
import { fmtDateTime, fmtWindow, tr } from "../../lib/format";
import { invalidate, useResource } from "../../lib/store";

type EventConflictsData = {
  closureId: string;
  inWindow: number;
  nearby: number;
  withoutVenue: number;
  summary: I18n;
  events: {
    id: string;
    title: string;
    venue: string | null;
    url: string | null;
    ongoing: boolean;
    overlap: { start: string; end: string };
    nearest: { kind: "stop" | "closure"; stopName: string | null; meters: number };
  }[];
  provenance: Provenance[];
};

export function EventConflicts({ closureId }: { closureId: string }) {
  const { t } = useTranslation();
  const key = `events:${closureId}`;
  const result = useResource<EventConflictsData>(key, () => apiGet<EventConflictsData>(`/api/closures/${encodeURIComponent(closureId)}/events`));
  const data = result.data;
  return <section>
    <h2>{tr({ ro: "Evenimente în perioada lucrării", en: "Events during the works" })}</h2>
    {!data ? <>
      <LoadState loading={result.loading} error={result.error} />
      {result.error && <button type="button" className="btn" onClick={() => invalidate(key)}>{tr({ ro: "Reîncearcă", en: "Retry" })}</button>}
    </> : <>
      <p className="small">{tr(data.summary)}</p>
      {data.withoutVenue > 0 && <p className="small muted">
        <Figure inline value={data.withoutVenue} provenance={data.provenance} /> {tr({ ro: "evenimente fără loc cunoscut: apropierea de lucrare este necunoscută.", en: "events have no known location: proximity to the works is unknown." })}
      </p>}
      <details>
        <summary>{t("details")}</summary>
        <p className="small muted">{tr({ ro: "În fereastră", en: "In the window" })}: <Figure inline value={data.inWindow} provenance={data.provenance} /> · {tr({ ro: "în apropiere", en: "nearby" })}: <Figure inline value={data.nearby} provenance={data.provenance} /></p>
        {data.events.length > 0 && <ul className="list small">
          {data.events.map((event) => <li key={event.id}>
            {event.url ? <a href={event.url} target="_blank" rel="noreferrer">{event.title}</a> : <strong>{event.title}</strong>}
            {event.ongoing && <span className="muted"> · {tr({ ro: "eveniment de lungă durată", en: "long-running event" })}</span>}
            <p>{event.venue ?? t("unknown")} · {fmtWindow(event.overlap)}</p>
            <p className="muted">
              <Figure inline value={event.nearest.meters} unit="m" provenance={data.provenance} /> {tr({ ro: "până la", en: "to" })} {event.nearest.kind === "stop" ? event.nearest.stopName ?? t("unknown") : tr({ ro: "tronsonul închis", en: "the closed section" })}
            </p>
          </li>)}
        </ul>}
        <p className="small muted">{tr({ ro: "Sursa", en: "Source" })}: {data.provenance.map((p) => `${p.source}${p.fetchedAt ? `, ${fmtDateTime(p.fetchedAt)}` : ""}`).join("; ")}</p>
      </details>
    </>}
  </section>;
}
