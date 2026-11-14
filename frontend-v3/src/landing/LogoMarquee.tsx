/**
 * The institutions and operators who close, repair and run services on Timișoara's streets: who the platform is made for.
 * Not a client list. Logos are shown where we have the official file; the rest are set as names.
 * Drop an official logo into public/logos/ and add `src` to switch a name to the mark.
 */
const ORGS: { name: string; src?: string; label?: boolean; h?: number }[] = [
  { name: "Primăria Municipiului Timișoara", src: "/logos/primaria-timisoara.png", label: true, h: 40 },
  { name: "STPT", src: "/logos/stpt.png", h: 30 },
  { name: "Poliția Locală Timișoara" },
  { name: "Aquatim" },
  { name: "Colterm" },
  { name: "ISU Banat" },
  { name: "Delgaz Grid" },
  { name: "Rețele Electrice", src: "/logos/retele-electrice.svg", h: 34 },
];

function Item({ o }: { o: (typeof ORGS)[number] }) {
  return (
    <li className="flex items-center gap-3 text-lg font-semibold tracking-tight text-muted-foreground">
      {o.src && (
        <img src={o.src} alt={o.label ? "" : o.name} style={{ height: o.h ?? 32 }} className="w-auto opacity-60 [filter:brightness(0)]" loading="lazy" />
      )}
      {(!o.src || o.label) && <span className="whitespace-nowrap">{o.name}</span>}
    </li>
  );
}

export function LogoStrip() {
  return (
    <section className="mx-auto max-w-6xl px-6 pt-24" aria-label="Pentru cine este făcută platforma">
      <p className="text-center text-[0.95rem] text-muted-foreground">
        Făcut pentru cei care închid, repară și circulă pe străzile Timișoarei
      </p>
      <ul className="mt-8 flex flex-wrap items-center justify-center gap-x-12 gap-y-6">
        {ORGS.map((o) => <Item key={o.name} o={o} />)}
      </ul>
      <p className="mt-6 text-center text-xs text-muted-foreground">Nu sunt parteneri și nu sunt clienți: sunt cei pentru care e gândită platforma.</p>
    </section>
  );
}
