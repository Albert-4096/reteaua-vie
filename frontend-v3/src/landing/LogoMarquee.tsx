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
    <li className="flex shrink-0 items-center gap-3 px-10 text-lg font-semibold tracking-tight text-foreground/55">
      {o.src && (
        <img src={o.src} alt={o.label ? "" : o.name} style={{ height: o.h ?? 32 }} className="w-auto opacity-60 [filter:brightness(0)]" loading="lazy" />
      )}
      {(!o.src || o.label) && <span className="whitespace-nowrap">{o.name}</span>}
    </li>
  );
}

export function LogoMarquee() {
  return (
    <section className="mx-auto max-w-6xl px-6 pt-24" aria-label="Pentru cine este făcută platforma">
      <p className="text-center text-[0.95rem] text-muted-foreground">
        Făcut pentru cei care închid, repară și circulă pe străzile Timișoarei
      </p>
      <div className="group relative mt-8 overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_12%,black_88%,transparent)]">
        <ul className="flex w-max animate-[marquee_48s_linear_infinite] items-center group-hover:[animation-play-state:paused] motion-reduce:animate-none">
          {ORGS.map((o) => <Item key={o.name} o={o} />)}
          {ORGS.map((o) => <Item key={`b-${o.name}`} o={o} />)}
        </ul>
      </div>
    </section>
  );
}
