import { useEffect, useId, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import type { Position } from "geojson";
import { Button } from "@/components/ui/button";
import { LineBadge } from "@/landing/LineBadge";
import { app, count, uniq, when, type ClosureSummary } from "../data";
import { go, link } from "../router";
import { Panel, Problem, Title, useMapLayers, type Layers } from "../ui";

/** A real STPT notice the platform already holds: its text can be tried without leaving the page. */
const EXAMPLE = "cl_20261107_e3";

const coords = (c: ClosureSummary | undefined): Position[] => (!c?.geometry ? [] : c.geometry.type === "LineString" ? c.geometry.coordinates : c.geometry.coordinates.flat());
/** "Anunț STPT: Strada Ardealului · linia E3 · din 07.11.2026" → "Strada Ardealului" */
const street = (title: string) => title.replace(/^Anunț STPT:\s*/, "").split(" · ")[0];

/**
 * How a work enters the platform: the notice is pasted as it was published, the platform reads the period,
 * the street and the lines with fixed rules, and a person checks what was understood before anything is computed.
 * `draftId` reopens a notice that was read earlier and left as a draft.
 */
export function NewWork({ draftId }: { draftId?: string }) {
  const field = useId();
  const [text, setText] = useState("");
  const [read, setRead] = useState<{ closure: ClosureSummary; unread: string[] | null } | null>(null);
  const [busy, setBusy] = useState<"read" | "compute" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [noStops, setNoStops] = useState(false);

  useEffect(() => {
    if (!draftId) return;
    let alive = true;
    app.closure(draftId)
      .then((c) => { if (alive) { setRead({ closure: c, unread: null }); setText(c.sourceText ?? ""); } })
      .catch((e: Error) => alive && setError(`Ciorna nu s-a încărcat (${e.message}).`));
    return () => { alive = false; };
  }, [draftId]);

  const c = read?.closure;
  const lines = useMemo(() => (c ? uniq([...(c.routeIds ?? []), ...(c.routeActions ?? []).map((a) => a.routeId)]) : []), [c]);
  const unclear = !!c && !c.geometry && lines.length === 0;

  const layers = useMemo<Layers>(() => {
    const p = coords(c), mid = p[Math.floor(p.length / 2)];
    if (!c || !mid) return { fit: { key: "city" }, highlight: lines };
    return {
      fit: { key: `new:${c.id}`, points: p, maxZoom: 14.6 },
      closures: [{ id: c.id, geometry: c.geometry, selected: true }],
      highlight: lines,
      labels: [{ id: "work", lon: mid[0], lat: mid[1], text: street(c.title.ro), tone: "work" }],
    };
  }, [c, lines]);
  useMapLayers(layers);

  const run = async (what: "read" | "compute", job: () => Promise<void>) => {
    setBusy(what); setError(null);
    try { await job(); } catch (e) { setError(`Serverul a răspuns cu o eroare (${(e as Error).message}). Încercați din nou.`); } finally { setBusy(null); }
  };
  const readIt = () => run("read", async () => { setNoStops(false); setRead(await app.parseNotice(text)); });
  const compute = () => run("compute", async () => {
    const a = await app.analyze(c!.id);
    if (a.stops.length === 0) { setNoStops(true); return; }
    go({ page: "lucrare", id: c!.id, tab: "impact" });
  });
  const example = async () => {
    setError(null);
    try { setText((await app.closure(EXAMPLE)).sourceText ?? ""); } catch (e) { setError(`Exemplul nu s-a încărcat (${(e as Error).message}).`); }
  };

  const back = (
    <a {...link({ page: "lucrari" })} className="-ml-1 inline-flex items-center gap-1 rounded-md px-1 text-sm text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
      <ArrowLeft className="size-3.5" /> Lucrări
    </a>
  );
  const head = <>{back}<div className="mt-2.5"><Title sub="Din anunțul lucrării, așa cum l-a publicat STPT sau Primăria.">Lucrare nouă</Title></div></>;

  if (!c) {
    return (
      <Panel head={head} foot={<Button className="h-11 w-full rounded-xl text-base" disabled={!text.trim() || busy === "read"} onClick={readIt}>{busy === "read" ? "Se citește anunțul…" : "Citește anunțul"}</Button>}>
        <label htmlFor={field} className="block text-sm font-semibold">Textul anunțului</label>
        <p className="mt-1 text-sm leading-relaxed text-muted-foreground">Copiați anunțul de la titlu până la ultima frază. Platforma îl citește cu reguli fixe, fără model de limbaj, și vă arată ce a înțeles înainte să calculeze ceva.</p>
        <textarea id={field} value={text} onChange={(e) => setText(e.target.value)} disabled={busy === "read"} spellCheck={false} rows={12}
          placeholder="Pentru desfășurarea în condiții de siguranță a lucrărilor…"
          className="mt-3 block w-full resize-y rounded-lg border bg-background px-3 py-2.5 text-sm leading-relaxed outline-none transition-colors placeholder:text-muted-foreground/70 focus-visible:border-foreground/40 focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-60" />
        {!text.trim() && !draftId && (
          <p className="mt-3 text-sm">
            <button type="button" onClick={example} className="rounded-sm font-medium underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-ring">Puneți un exemplu</button>
            <span className="text-muted-foreground">: anunțul STPT despre Strada Ardealului, din noiembrie.</span>
          </p>
        )}
        {error && <div className="mt-4"><Problem>{error}</Problem></div>}
      </Panel>
    );
  }

  return (
    <Panel head={head}
      foot={unclear || noStops ? undefined : <Button className="h-11 w-full rounded-xl text-base" disabled={busy === "compute"} onClick={compute}>{busy === "compute" ? "Se calculează…" : <>Calculează impactul <ArrowRight className="size-4" /></>}</Button>}>
      <p className="text-[1.05rem] font-medium leading-snug">{c.title.ro}</p>
      <dl className="mt-5 divide-y border-y text-sm">
        <div className="flex gap-4 py-2.5"><dt className="w-20 shrink-0 text-muted-foreground">Perioadă</dt><dd className="tabular min-w-0">{when(c.window)}</dd></div>
        <div className="flex gap-4 py-2.5">
          <dt className="w-20 shrink-0 text-muted-foreground">Linii</dt>
          <dd className="min-w-0">
            {lines.length > 0 ? <span className="flex flex-wrap gap-1">{lines.map((r) => <LineBadge key={r} routeId={r} />)}{(c.temporaryRoutes ?? []).map((t) => <span key={t.shortName} className="inline-flex h-6 items-center rounded-md border border-dashed px-1.5 text-xs font-medium">{t.shortName}</span>)}</span> : "Nicio linie numită: se iau toate liniile de pe stradă."}
          </dd>
        </div>
        <div className="flex gap-4 py-2.5"><dt className="w-20 shrink-0 text-muted-foreground">Strada</dt><dd className="min-w-0">{c.geometry ? "Găsită și desenată pe hartă." : "Negăsită în text."}</dd></div>
      </dl>
      {c.locationNote?.ro && <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{c.locationNote.ro}</p>}

      {read.unread && (read.unread.length > 0 ? (
        <div className="mt-6">
          <p className="text-sm font-semibold">{read.unread.length === 1 ? "O frază nu a putut fi citită" : `${count(read.unread.length, "frază", "fraze")} nu au putut fi citite`}</p>
          <ul className="mt-2 space-y-2 border-l-2 border-foreground/20 pl-3 text-sm leading-relaxed text-foreground/80">
            {read.unread.map((s, i) => <li key={i}>„{s}”</li>)}
          </ul>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">Nu intră în calcul. Dacă una numește o stație sau o linie, verificați-o la pasul următor.</p>
        </div>
      ) : (
        <p className="mt-5 flex items-center gap-2 text-sm text-accent-foreground"><Check className="size-4" />Am citit toate frazele anunțului.</p>
      ))}

      {unclear && <div className="mt-5"><Problem>Nu am găsit în text nici strada, nici liniile afectate, deci stațiile nu pot fi calculate. Verificați dacă ați lipit tot anunțul.</Problem></div>}
      {noStops && <div className="mt-5"><Problem>Din ce am citit, analiza nu a găsit nicio stație afectată. Anunțul trebuie verificat de un om.</Problem></div>}
      {error && <div className="mt-5"><Problem>{error}</Problem></div>}

      <p className="mt-6 text-xs leading-relaxed text-muted-foreground">
        Ce s-a citit e păstrat ca ciornă în Lucrări.{" "}
        <button type="button" disabled={busy === "compute"} onClick={() => { setRead(null); setNoStops(false); setError(null); }} className="rounded-sm font-medium text-foreground underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-ring">Lipiți alt text</button>
      </p>
    </Panel>
  );
}
