/** What nobody can see today: three sourced facts. The wording is fixed (safe formulations); do not paraphrase. */
const ROWS = [
  {
    label: "Lucrări",
    fact: "Anunțul STPT pentru 8 nov spune ce linii se schimbă. Nu spune câte plecări se pierd, nici ce stații rămân fără transport.",
    source: "Anunțul de pe stpt.ro, lucrările de pe Bd. 16 Decembrie 1989",
  },
  {
    label: "Linii",
    fact: "Sâmbătă dimineață, niciun vehicul al liniei 23 nu a apărut în datele live ale Primăriei, deși orarul avea 19 curse până la 10:41. CityApp a arătat ora din orar.",
    source: "Din datele live ale Primăriei, înregistrate de noi · 14 nov, 06:00–10:41",
  },
  {
    label: "Plăți",
    fact: "SMTT plătește compensația pe raportul lunar al STPT, pornind de la kilometri și curse.",
    source: "Contractul de servicii publice 1812/2020, art. 12.3–12.6",
  },
];

export function Today() {
  return (
    <section id="azi" className="mx-auto max-w-4xl scroll-mt-24 px-6 pt-28">
      <h2 className="display text-[2.75rem]">Ce nu se vede azi</h2>
      <dl className="mt-10 border-t">
        {ROWS.map((r) => (
          <div key={r.label} className="grid gap-x-8 gap-y-2 border-b py-6 md:grid-cols-[200px_1fr]">
            <dt className="text-lg font-semibold tracking-tight">{r.label}</dt>
            <dd>
              <p className="max-w-[62ch] text-lg leading-relaxed">{r.fact}</p>
              <p className="mt-2 text-sm text-muted-foreground">{r.source}</p>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
