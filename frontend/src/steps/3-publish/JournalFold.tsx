// R13-F: evidence journal. Lists only the acts the response returns.
import { journal, journalBundlePath, type Journal } from "../../api/journal";
import { LoadState } from "../../components/Panel";
import { fmtDateTime, tr } from "../../lib/format";
import { useResource } from "../../lib/store";

const C = {
  title: { ro: "Jurnal", en: "Journal" },
  empty: { ro: "Jurnalul este gol.", en: "The journal is empty." },
  bundle: { ro: "pachet pentru rulare din nou", en: "bundle to run again" },
};

const KIND: Record<string, { ro: string; en: string }> = {
  decision: { ro: "decizie", en: "decision" },
  publish: { ro: "publicare", en: "publish" },
  triage: { ro: "triere", en: "triage" },
};

export function JournalFold({ closureId }: { closureId: string }) {
  const res = useResource<Journal>(`journal:${closureId}`, () => journal(closureId));
  const j = res.data;
  return (
    <details>
      <summary>{tr(C.title)}</summary>
      {!j ? (
        <LoadState loading={res.loading} error={res.error} />
      ) : (
        <>
          {j.entries.length === 0 ? (
            <p className="small muted">{tr(C.empty)}</p>
          ) : (
            <ul className="list small">
              {j.entries.map((e) => (
                <li key={e.n}>
                  {fmtDateTime(e.at)}
                  {" · "}
                  {tr(KIND[e.kind] ?? { ro: e.kind, en: e.kind })}
                  {" · "}
                  {tr(e.summary)}
                  {" · "}
                  {e.feedVersion}
                  {" · "}
                  <span className="mono" title={e.hash}>
                    {e.hash.slice(0, 8)}…
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="small" style={{ marginTop: "var(--sp-2)" }}>
            <a href={journalBundlePath(closureId)} target="_blank" rel="noreferrer">
              {tr(C.bundle)}
            </a>
          </p>
        </>
      )}
    </details>
  );
}
