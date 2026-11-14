// C1: simulated on-board check-in, only in the missing-lines view. Nothing is sent until the button is pressed.
import { useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { deviceKey, postCheckin, type CheckinAck } from "../../api/checkin";
import { ApiError } from "../../api/client";
import { tr } from "../../lib/format";
import "./checkin.css";

const copy = {
  title: { ro: "Check-in (simulare)", en: "Check-in (simulation)" },
  sticker: { ro: "Autocolant", en: "Sticker" },
  button: { ro: "Check-in (simulare)", en: "Check-in (simulation)" },
  note: { ro: "Numărătoare paralelă, nu validarea oficială.", en: "A parallel count, not the official validation." },
  line: (name: string) => ({ ro: `Linia ${name}`, en: `Line ${name}` }),
  position: { ro: "poziție", en: "position" },
  time: { ro: "oră", en: "time" },
  simulated: { ro: "simulare", en: "simulation" },
  sending: { ro: "Se trimite…", en: "Sending…" },
};

function methodWord(method: CheckinAck["method"]) {
  if (method === "position") return copy.position;
  if (method === "time") return copy.time;
  return null;
}

/** The ack label, with „simulare” whenever the sticker is a test sticker. */
function ackLabel(ack: CheckinAck, unknown: string): string {
  const text = ack.label ? tr(ack.label) : "";
  if (!ack.simulated) return text || unknown;
  if (/simulare|simulation/i.test(text)) return text;
  const mark = tr(copy.simulated);
  return text ? `${text} · ${mark}` : mark;
}

export function CheckinSim() {
  const { t } = useTranslation();
  const [sticker, setSticker] = useState("test-l23");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ack, setAck] = useState<CheckinAck | null>(null);
  const pending = useRef(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    const stickerId = sticker.trim();
    if (!stickerId) return;
    pending.current = true;
    setBusy(true);
    setError(null);
    try {
      setAck(await postCheckin(stickerId, deviceKey()));
    } catch (e) {
      setAck(null);
      setError(e instanceof ApiError ? `${e.code}: ${e.message}` : e instanceof Error ? e.message : String(e));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  const method = ack ? methodWord(ack.method) : null;
  return (
    <form className="checkin" onSubmit={submit} aria-label={tr(copy.title)}>
      <h2>{tr(copy.title)}</h2>
      <p className="small muted">{tr(copy.note)}</p>
      <fieldset disabled={busy}>
        <legend className="visually-hidden">{tr(copy.button)}</legend>
        <label>
          {tr(copy.sticker)}
          <input
            name="stickerId"
            value={sticker}
            onChange={(e) => setSticker(e.target.value)}
            autoComplete="off"
            required
            maxLength={40}
            spellCheck={false}
          />
        </label>
        <button type="submit" className="btn" disabled={busy || sticker.trim() === ""}>
          {tr(copy.button)}
        </button>
      </fieldset>
      {busy && (
        <p className="small" role="status">
          {tr(copy.sending)}
        </p>
      )}
      {error && (
        <p className="error-msg" role="alert">
          {error}
        </p>
      )}
      {ack && (
        <p className="small" role="status">
          {ack.shortName ? tr(copy.line(ack.shortName)) : t("unknown")}
          {" · "}
          <span className="mono">{ack.routeId || t("unknown")}</span>
          {" · "}
          <span className="mono">{ack.tripId || t("unknown")}</span>
          {" · "}
          {method ? tr(method) : t("unknown")}
          {" · "}
          {ackLabel(ack, t("unknown"))}
        </p>
      )}
    </form>
  );
}
