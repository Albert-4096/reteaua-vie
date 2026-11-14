import { ExternalLink } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApi } from "@/lib/api";
import { app, day, fmt, hhmm } from "../data";
import { Loading, Method, Problem, Stat, Tag, Title } from "../ui";

const OBL = { covered: ["green", "Acoperit"], partial: ["neutral", "Parțial"], missing: ["closure", "Lipsește"] } as const;
const TH = "px-4 py-3 font-medium";

/** What leaves the platform as a report: obligations, past works, indicators, the public files. No map here. */
export function Reports() {
  const comp = useApi(app.compliance);
  const ind = useApi(app.indicators);
  const hist = useApi(app.history);
  const exp = useApi(app.exports);
  const reg = useApi(app.registry);
  const by = (s: string) => comp.data?.obligations.filter((o) => o.status === s).length ?? 0;

  return (
    <div tabIndex={0} role="region" aria-label="Rapoarte" className="h-full overflow-y-auto outline-none">
      <div className="mx-auto w-full max-w-5xl px-6 pb-24 pt-8 md:px-10">
        <Title sub="Obligațiile de informare a călătorilor și fișierul platformei care răspunde fiecăreia. Pentru SMTT, Primărie și Punctul Național de Acces.">Rapoarte</Title>
        {comp.error ? <div className="mt-6"><Problem>Obligațiile nu s-au încărcat ({comp.error}).</Problem></div> : comp.data && (
          <dl className="mt-7 flex gap-12">
            <Stat value={fmt.format(comp.data.obligations.length)} label="obligații UE și naționale" />
            <Stat value={fmt.format(by("covered"))} label={by("covered") === 1 ? "acoperită" : "acoperite"} tone="green" />
            <Stat value={fmt.format(by("partial"))} label="parțial" />
            <Stat value={fmt.format(by("missing"))} label={by("missing") === 1 ? "lipsește" : "lipsesc"} tone="closure" />
          </dl>
        )}

        <Tabs defaultValue="obl" className="mt-9">
          <TabsList>
            <TabsTrigger value="obl">Obligații</TabsTrigger>
            <TabsTrigger value="reg">Registrul curselor</TabsTrigger>
            <TabsTrigger value="hist">Lucrări anterioare</TabsTrigger>
            <TabsTrigger value="ind">Indicatori</TabsTrigger>
            <TabsTrigger value="files">Fișiere publice</TabsTrigger>
          </TabsList>
          <TabsContent value="obl" className="mt-4">
            {!comp.data ? <Loading /> : (
              <div tabIndex={0} role="region" aria-label="Tabel, se derulează orizontal" className="overflow-x-auto rounded-xl border outline-none focus-visible:ring-2 focus-visible:ring-ring/60">
                <table className="w-full min-w-[40rem] text-left text-sm">
                  <thead className="bg-muted/60 text-muted-foreground"><tr><th className={TH}>Act</th><th className={TH}>Cerința</th><th className={TH}>Termen</th><th className={TH}>Stare</th></tr></thead>
                  <tbody className="divide-y">
                    {comp.data.obligations.map((o) => {
                      const [tone, label] = OBL[o.status as keyof typeof OBL] ?? ["neutral", o.status];
                      return (
                        <tr key={o.id} className="align-top">
                          <td className="px-4 py-3 font-medium">{o.act}</td>
                          <td className="px-4 py-3"><div>{o.requirement.ro}</div>{o.note?.ro && <div className="mt-1 text-xs text-muted-foreground">{o.note.ro}</div>}</td>
                          <td className="tabular whitespace-nowrap px-4 py-3 text-muted-foreground">{o.deadline}</td>
                          <td className="px-4 py-3"><Tag tone={tone as "green"}>{label}</Tag></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </TabsContent>
          <TabsContent value="reg" className="mt-4">
            {reg.error ? <Problem>Registrul nu s-a încărcat ({reg.error}).</Problem> : !reg.data ? <Loading /> : (
              <div tabIndex={0} role="region" aria-label="Tabel, se derulează orizontal" className="overflow-x-auto rounded-xl border outline-none focus-visible:ring-2 focus-visible:ring-ring/60">
                <table className="w-full min-w-[40rem] text-left text-sm">
                  <thead className="bg-muted/60 text-muted-foreground"><tr><th className={TH}>Ziua</th><th className={TH}>Înregistrat</th><th className={`${TH} text-right`}>Curse văzute</th><th className={`${TH} text-right`}>Din orar</th><th className={`${TH} text-right`}>Km, estimare</th><th className={TH}>Stare</th></tr></thead>
                  <tbody className="tabular divide-y">
                    {reg.data.entries.map((e) => {
                      const seen = e.lines.reduce((n, l) => n + l.tripsSeen, 0), sched = e.lines.reduce((n, l) => n + l.tripsScheduledInRecording, 0);
                      const km = e.lines.reduce((n, l) => n + (l.kmEstimated ?? 0), 0);
                      return (
                        <tr key={e.date}>
                          <td className="px-4 py-3 font-medium">{day(e.date)}</td>
                          <td className="px-4 py-3 text-muted-foreground">{hhmm(e.recording.firstAt)}–{hhmm(e.recording.lastAt)}</td>
                          <td className="px-4 py-3 text-right font-semibold">{fmt.format(seen)}</td>
                          <td className="px-4 py-3 text-right">{fmt.format(sched)}</td>
                          <td className="px-4 py-3 text-right">{fmt.format(Math.round(km))}</td>
                          <td className="px-4 py-3">{e.final ? <Tag tone="green">Închisă</Tag> : <Tag>În curs</Tag>} <span className="ml-1 font-mono text-xs text-muted-foreground" title={`lanț: ${e.chainHash}`}>{e.chainHash.slice(0, 10)}</span></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <Method>Curse din orar văzute în datele live ale Primăriei, pe zi. O zi închisă e scrisă o singură dată și legată de cea dinainte printr-un lanț de sume de control, deci nu poate fi schimbată fără să se vadă. Estimare din datele live, nu raportul oficial: cursele le încadrează SMTT.</Method>
          </TabsContent>
          <TabsContent value="hist" className="mt-4">
            {!hist.data ? <Loading /> : (
              <div tabIndex={0} role="region" aria-label="Tabel, se derulează orizontal" className="overflow-x-auto rounded-xl border outline-none focus-visible:ring-2 focus-visible:ring-ring/60">
                <table className="w-full min-w-[40rem] text-left text-sm">
                  <thead className="bg-muted/60 text-muted-foreground"><tr><th className={TH}>Lucrarea</th><th className={TH}>Început</th><th className={`${TH} text-right`}>Anunț înainte</th><th className={`${TH} text-right`}>Plecări pierdute</th></tr></thead>
                  <tbody className="divide-y">
                    {hist.data.map((h) => (
                      <tr key={h.closureId}>
                        <td className="px-4 py-3"><a href={h.sourceUrl} target="_blank" rel="noreferrer" className="font-medium underline-offset-4 hover:underline">{h.title.ro}</a></td>
                        <td className="tabular px-4 py-3 text-muted-foreground">{day(h.window.start)}</td>
                        <td className="tabular px-4 py-3 text-right">{h.leadHours != null ? `${fmt.format(Math.round(h.leadHours))} h` : "–"}</td>
                        <td className="tabular px-4 py-3 text-right">{fmt.format(h.departuresLost)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <Method>Reconstituit din anunțurile STPT; plecările pierdute sunt o estimare pe orarul planificat.</Method>
          </TabsContent>
          <TabsContent value="ind" className="mt-4">
            {!ind.data ? <Loading /> : (
              <dl className="divide-y rounded-xl border">
                {ind.data.indicators.map((i) => (
                  <div key={i.code} className="flex items-baseline justify-between gap-4 px-4 py-3 text-sm">
                    <dt>{i.name.ro}</dt><dd className="tabular whitespace-nowrap font-semibold">{fmt.format(Math.round(i.value * 10) / 10)} {i.unit}</dd>
                  </div>
                ))}
              </dl>
            )}
          </TabsContent>
          <TabsContent value="files" className="mt-4">
            {!exp.data ? <Loading /> : (
              <ul className="divide-y rounded-xl border">
                {exp.data.map((x) => (
                  <li key={x.name} className="flex items-center justify-between gap-4 px-4 py-3 text-sm">
                    <span><span className="font-medium">{x.format}</span><span className="block text-xs text-muted-foreground">{x.standard}</span></span>
                    <a href={x.url} target="_blank" rel="noreferrer" className="inline-flex shrink-0 items-center gap-1 font-medium text-accent-foreground underline-offset-4 hover:underline">{x.name} <ExternalLink className="size-3.5" /></a>
                  </li>
                ))}
              </ul>
            )}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
