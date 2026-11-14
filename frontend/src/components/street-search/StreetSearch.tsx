// R1-F(b): a registered street and a chosen section become a draft closure, then the normal review flow.
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, apiSend, ApiError, type Analysis, type Closure, type Health } from "../../api/client";
import { cityInput, cityInstant, streets, type MapPoint, type StreetHit, type StreetSearchResult, type StreetSection } from "../../api/streets";
import { tr } from "../../lib/format";
import { navigate } from "../../lib/router";
import { invalidate, setData, useResource } from "../../lib/store";
import { Figure } from "../Figure";
import { useMapOverlay, type MapStop } from "../MapView";
import { LoadState } from "../Panel";
import { S } from "./strings";
import "./street-search.css";

function message(error: unknown) {
  if (error instanceof ApiError) {
    if (error.code === "NOT_ON_STREET") return `${tr(S.notOnStreet)} ${error.message} (${error.code})`;
    if (error.code === "EMPTY_SECTION") return `${tr(S.emptySection)} ${error.message} (${error.code})`;
    return `${error.message || error.code} (${error.code})`;
  }
  return error instanceof Error ? error.message : String(error);
}

export function StreetSearch() {
  const { t } = useTranslation();
  const health = useResource<Health>("health", () => api.health());
  const initialized = useRef(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<StreetSearchResult | null>(null);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<StreetHit | null>(null);
  const [whole, setWhole] = useState<StreetSection | null>(null);
  const [section, setSection] = useState<StreetSection | null>(null);
  const [points, setPoints] = useState<MapPoint[]>([]);
  const [wholeChosen, setWholeChosen] = useState(false);
  const [sectionBusy, setSectionBusy] = useState(false);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Closure | null>(null);
  const searchGen = useRef(0);
  const lock = useRef(false);

  useEffect(() => {
    if (initialized.current || health.loading) return;
    initialized.current = true;
    const from = health.data?.demoNow ?? new Date().toISOString();
    setStart(cityInput(from));
    setEnd(cityInput(new Date(Date.parse(from) + 8 * 3_600_000).toISOString()));
  }, [health.data, health.loading]);

  useEffect(() => {
    if (!selected) return;
    let active = true;
    setSectionBusy(true);
    streets.section(selected.streetId)
      .then((value) => { if (active) setWhole(value); })
      .catch((e) => { if (active) setError(message(e)); })
      .finally(() => { if (active) setSectionBusy(false); });
    return () => { active = false; };
  }, [selected?.streetId]);

  useEffect(() => {
    if (!selected || points.length !== 2 || wholeChosen) return;
    let active = true;
    setSectionBusy(true);
    streets.section(selected.streetId, points)
      .then((value) => { if (active) setSection(value); })
      .catch((e) => { if (active) setError(message(e)); })
      .finally(() => { if (active) setSectionBusy(false); });
    return () => { active = false; };
  }, [selected?.streetId, points, wholeChosen]);

  const click = useCallback((point: MapPoint) => {
    setPoints((previous) => previous.length >= 2 ? [point] : [...previous, point]);
    setSection(null); setCreated(null); setError(null);
  }, []);
  const chosen = wholeChosen ? whole : section;
  const preview = chosen ?? whole;
  const markers: MapStop[] = points.map((location, index) => ({
    id: `street-end-${index}`, location, name: tr(index === 0 ? S.startPoint : S.endPoint),
    label: tr(index === 0 ? S.startPoint : S.endPoint), status: "served",
  }));
  const overlay = {
    closure: preview?.geometry, stops: markers,
    fitKey: preview ? `street:${preview.streetId}:${preview.whole ? "whole" : preview.lengthMeters}` : undefined,
    note: selected ? tr(wholeChosen ? S.wholeSelected : points.length === 0 ? S.chooseStart : points.length === 1 ? S.chooseEnd : S.selected) : undefined,
    onMapClick: selected && whole && !wholeChosen && !busy && !sectionBusy ? click : undefined,
  };
  useMapOverlay(overlay, [preview, selected?.streetId, points, wholeChosen, busy, sectionBusy, t]);

  async function search() {
    const id = ++searchGen.current;
    setSearching(true); setError(null);
    try {
      const value = await streets.search(query.trim());
      if (searchGen.current === id) setResults(value);
    } catch (e) {
      if (searchGen.current === id) setError(message(e));
    } finally {
      if (searchGen.current === id) setSearching(false);
    }
  }

  function pick(street: StreetHit) {
    if (selected?.streetId === street.streetId) { chooseAgain(); return; }
    setSelected(street); setWhole(null); setSection(null); setPoints([]);
    setWholeChosen(false); setCreated(null); setError(null);
  }

  function chooseAgain() {
    setPoints([]); setSection(null); setWholeChosen(false); setCreated(null); setError(null);
  }

  async function analyze() {
    if (lock.current) return;
    const from = cityInstant(start), until = cityInstant(end);
    if (!from || !until || Date.parse(until) <= Date.parse(from)) { setError(tr(S.invalidWindow)); return; }
    if (!chosen || !selected) return;
    lock.current = true;
    setBusy(true); setError(null); setPending(false);
    try {
      const closure = created ?? await apiSend<Closure>("POST", "/api/closures", {
        title: { ro: `Lucrări pe ${selected.name}`, en: `Works on ${selected.name}` },
        kind: "drawn", geometry: chosen.geometry, bufferMeters: 30, direction: "both",
        window: { start: from, end: until }, routeIds: null, sourceText: null, sourceUrl: null,
        routeActions: null, temporaryRoutes: null,
      });
      setCreated(closure);
      setPending(true);
      const analysis = await apiSend<Analysis>("POST", `/api/closures/${encodeURIComponent(closure.id)}/analyze`);
      setData(`analysis:${closure.id}`, analysis);
      invalidate(`closure:${closure.id}`, "closures");
      navigate(`/step/1?case=${encodeURIComponent(closure.id)}`);
    } catch (e) { setError(message(e)); }
    finally { lock.current = false; setBusy(false); setPending(false); }
  }

  return (
    <section className="street-search" aria-label={tr(S.label)}>
      <form className="street-search-form" onSubmit={(e) => { e.preventDefault(); void search(); }}>
        <label htmlFor="street-query">{tr(S.label)}
          <input id="street-query" value={query} minLength={2} required disabled={busy || searching} onChange={(e) => setQuery(e.target.value)} aria-describedby="street-hint" />
        </label>
        <button type="submit" className="btn" disabled={query.trim().length < 2 || searching || busy}>{tr(S.search)}</button>
      </form>
      <p id="street-hint" className="small muted">{tr(S.hint)}</p>
      <LoadState loading={searching || sectionBusy} pending={pending} />
      {results && !results.streets.length && <p className="small muted">{tr(S.none)}</p>}
      {results && results.streets.length > 0 && <ul className="street-search-results list">
        {results.streets.map((street) => <li key={street.streetId}>
          <button type="button" className="row-button" disabled={!street.hasGeometry || busy || sectionBusy} aria-pressed={selected?.streetId === street.streetId} onClick={() => pick(street)}>
            <span>{street.name}{street.formerName && <span className="small muted"> · {tr(S.former)}: {street.formerName}</span>}{!street.hasGeometry && <span className="small muted"> · {tr(S.noGeometry)}</span>}</span>
          </button>
        </li>)}
      </ul>}
      {selected && <>
        <h2>{selected.name}</h2>
        <p className="small" role="status">{tr(wholeChosen ? S.wholeSelected : points.length === 0 ? S.chooseStart : points.length === 1 ? S.chooseEnd : S.selected)}</p>
        <div className="street-search-actions">
          <button type="button" className="btn" disabled={!whole || busy || sectionBusy} onClick={() => { setWholeChosen(true); setPoints([]); setSection(null); setCreated(null); setError(null); }}>{tr(S.whole)}</button>
          <button type="button" className="linklike small" disabled={busy || sectionBusy} onClick={chooseAgain}>{tr(S.sectionAgain)}</button>
        </div>
        {chosen && <p className="small">{tr(S.selected)}: <Figure inline value={chosen.lengthMeters} unit="m" provenance={chosen.provenance} /></p>}
        <div className="street-search-window">
          <label htmlFor="street-start">{tr(S.start)}<input id="street-start" type="datetime-local" required value={start} disabled={busy} onChange={(e) => { setStart(e.target.value); setCreated(null); }} /></label>
          <label htmlFor="street-end">{tr(S.end)}<input id="street-end" type="datetime-local" required value={end} disabled={busy} onChange={(e) => { setEnd(e.target.value); setCreated(null); }} /></label>
        </div>
        <p className="small muted">{tr(S.drawnCaveat)}</p>
        <button type="button" className="btn btn-primary" disabled={!chosen || busy || sectionBusy || !start || !end} onClick={() => void analyze()}>{tr(busy ? S.creating : S.analyze)}</button>
      </>}
      {error && <p className="error-msg small" role="alert">{tr(S.error)}: {error}</p>}
    </section>
  );
}
