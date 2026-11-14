// Paste-a-notice text (R1-F a), Romanian first. Rendered with tr() so the language switch applies.
export const S = {
  label: { ro: "Lipește textul unui anunț STPT", en: "Paste the text of an STPT notice" },
  hint: {
    ro: "Copiază anunțul de pe stpt.ro, de la titlu până la ultima frază. Îl citim fără inteligență artificială.",
    en: "Copy the notice from stpt.ro, from the title to the last sentence. We read it without AI.",
  },
  read: { ro: "Citește anunțul", en: "Read the notice" },
  reading: { ro: "citim anunțul…", en: "reading the notice…" },
  window: { ro: "Interval", en: "Window" },
  lines: { ro: "Linii", en: "Lines" },
  noLines: { ro: "nicio linie numită; luăm toate liniile de pe stradă", en: "no line named; we take every line on the street" },
  street: { ro: "Strada pe hartă", en: "Street on the map" },
  streetFound: { ro: "găsită, desenată pe hartă", en: "found, drawn on the map" },
  streetMissing: { ro: "negăsită", en: "not found" },
  unreadTitle: (n: number) =>
    n === 1
      ? { ro: "O frază nu a putut fi citită:", en: "One sentence could not be read:" }
      : { ro: `${n} fraze nu au putut fi citite:`, en: `${n} sentences could not be read:` },
  unreadHint: {
    ro: "Nu le folosim în calcul. Dacă numesc o stație sau o linie, verific-o în pasul următor.",
    en: "They are not used in the analysis. If one names a stop or a line, check it in the next step.",
  },
  allRead: { ro: "Am citit toate frazele anunțului.", en: "Every sentence of the notice was read." },
  unclear: {
    ro: "Nu am găsit în text nici strada, nici liniile afectate, deci nu putem calcula stațiile. Verifică dacă ai lipit tot anunțul.",
    en: "We found neither the street nor the affected lines in the text, so we cannot work out the stops. Check that you pasted the whole notice.",
  },
  noStops: {
    ro: "Analiza nu a găsit nicio stație afectată din ce am citit. Frazele de mai sus nu intră în calcul, deci anunțul trebuie verificat de un om.",
    en: "The analysis found no affected stop in what we read. The sentences above are not used, so a person must check the notice.",
  },
  analyze: { ro: "Vezi stațiile afectate", en: "See the affected stops" },
  computing: { ro: "calculăm…", en: "computing…" },
  again: { ro: "Lipește alt text", en: "Paste another text" },
  error: (msg: string) => ({ ro: `Serverul a răspuns cu o eroare: ${msg}`, en: `The server answered with an error: ${msg}` }),
};
