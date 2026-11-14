// R1-F (a): paste a real STPT notice → POST /api/closures/parse (no LLM) → the official reviews what was read
// and the sentences that were not → POST /api/closures/{id}/analyze → step 1 with the affected stops.
import { useState } from "react";
import { ApiError, apiSend, api, type Analysis, type Closure, type Network } from "../../api/client";
import { fmtWindow, tr } from "../../lib/format";
import { navigate } from "../../lib/router";
import { setData, useResource } from "../../lib/store";
import { useMapOverlay } from "../MapView";
import { S } from "./strings";
import "./paste-notice.css";

type Parsed = { closure: Closure; unread: string[] };
type Phase = "idle" | "reading" | "read" | "computing";

const apiMessage = (e: unknown) =>
  e instanceof ApiError ? `${e.message || e.code} (${e.code})` : e instanceof Error ? e.message : String(e);

export function PasteNotice() {
  const [text, setText] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [parsed, setParsed] = useState<Parsed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [noStops, setNoStops] = useState(false);
  const network = useResource<Network>("network", () => api.network());

  const c = parsed?.closure;
  const lineIds = c ? [...new Set([...(c.routeIds ?? []), ...(c.routeActions ?? []).map((a) => a.routeId)])] : [];
  useMapOverlay(
    { closure: (c?.geometry as GeoJSON.Geometry | null) ?? null, highlightRouteIds: lineIds, fitKey: c?.id },
    [c?.id],
  );

  async function read() {
    setPhase("reading");
    setError(null);
    try {
      setParsed(await apiSend<Parsed>("POST", "/api/closures/parse", { text }));
      setPhase("read");
    } catch (e) {
      setError(apiMessage(e));
      setPhase("idle");
    }
  }

  async function analyze(id: string) {
    setPhase("computing");
    setError(null);
    try {
      const a = await apiSend<Analysis>("POST", `/api/closures/${encodeURIComponent(id)}/analyze`);
      if (a.stops.length === 0) {
        setNoStops(true);
        setPhase("read");
        return;
      }
      setData(`analysis:${id}`, a);
      navigate(`/step/1?case=${encodeURIComponent(id)}`);
    } catch (e) {
      setError(apiMessage(e));
      setPhase("read");
    }
  }

  if (!c || !parsed) {
    return (
      <section className="paste" aria-labelledby="paste-label">
        <label id="paste-label" htmlFor="paste-text">
          {tr(S.label)}
        </label>
        <p className="small muted">{tr(S.hint)}</p>
        <textarea
          id="paste-text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={phase === "reading"}
          spellCheck={false}
        />
        <div className="paste-actions">
          <button type="button" className="btn" disabled={!text.trim() || phase === "reading"} onClick={() => void read()}>
            {tr(S.read)}
          </button>
          {phase === "reading" && (
            <p className="state-msg small" role="status">
              {tr(S.reading)}
            </p>
          )}
          {error && <p className="error-msg small">{tr(S.error(error))}</p>}
        </div>
      </section>
    );
  }

  const short = (id: string) => network.data?.routes.find((r) => r.id === id)?.shortName ?? id;
  const temp = (c.temporaryRoutes ?? []).map((r) => r.shortName);
  const unclear = !c.geometry && lineIds.length === 0;
  const busy = phase === "computing";

  return (
    <section className="paste" aria-labelledby="paste-title">
      <h2 id="paste-title">{tr(c.title)}</h2>
      <dl className="paste-facts small">
        <dt>{tr(S.window)}</dt>
        <dd>{fmtWindow(c.window)}</dd>
        <dt>{tr(S.lines)}</dt>
        <dd>{lineIds.length > 0 ? [...lineIds.map(short), ...temp].join(", ") : tr(S.noLines)}</dd>
        <dt>{tr(S.street)}</dt>
        <dd>{c.geometry ? tr(S.streetFound) : tr(S.streetMissing)}</dd>
      </dl>
      {c.locationNote && <p className="small muted">{tr(c.locationNote)}</p>}

      {parsed.unread.length > 0 ? (
        <div className="paste-unread small">
          <p>
            <strong>{tr(S.unreadTitle(parsed.unread.length))}</strong>
          </p>
          <ul>
            {parsed.unread.map((s, i) => (
              <li key={i}>„{s}”</li>
            ))}
          </ul>
          <p className="muted">{tr(S.unreadHint)}</p>
        </div>
      ) : (
        <p className="small muted">{tr(S.allRead)}</p>
      )}

      {unclear && <p className="error-msg small">{tr(S.unclear)}</p>}
      {noStops && <p className="error-msg small">{tr(S.noStops)}</p>}

      <div className="paste-actions">
        {!unclear && !noStops && (
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void analyze(c.id)}>
            {tr(S.analyze)}
          </button>
        )}
        {busy && (
          <p className="state-msg small" role="status">
            {tr(S.computing)}
          </p>
        )}
        {error && <p className="error-msg small">{tr(S.error(error))}</p>}
        <button
          type="button"
          className="linklike small"
          disabled={busy}
          onClick={() => {
            setParsed(null);
            setPhase("idle");
            setError(null);
            setNoStops(false);
          }}
        >
          {tr(S.again)}
        </button>
      </div>
    </section>
  );
}
