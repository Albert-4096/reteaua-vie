// Step 5 text, Romanian first. Rendered with tr() so the language switch applies.
export const S = {
  title: { ro: "Ce trimitem la UE?", en: "What do we send to the EU?" },
  sentence: {
    ro: "Ce acoperă fișierele publicate de platformă din obligațiile UE. Spune ce acoperă exporturile noastre, nu că orașul e conform.",
    en: "What the platform's published files cover of the EU obligations. It says what our exports cover, not that the city complies.",
  },
  obligation: { ro: "Obligația", en: "Obligation" },
  status: { ro: "Acoperire", en: "Coverage" },
  st: {
    covered: { ro: "acoperit", en: "covered" },
    partial: { ro: "parțial", en: "partly" },
    missing: { ro: "lipsă", en: "missing" },
  },
  nap: { ro: "Descarcă metadatele NAP", en: "Download the NAP metadata" },
  history: { ro: "Istoricul perturbărilor", en: "Disruption history" },
  backfilled: { ro: "reconstituit", en: "reconstructed" },
  viaPlatform: { ro: "publicat prin platformă", en: "published through the platform" },
  source: { ro: "anunțul STPT", en: "STPT notice" },
  indicators: { ro: "Indicatori PMUD / TEN-T", en: "SUMP / TEN-T indicators" },
  exports: { ro: "Toate fișierele publicate", en: "All published files" },
  // R6-F: step-free vehicles per line, from our recording of the City Hall feed.
  acc: {
    title: { ro: "Vehicule accesibile, pe linii", en: "Step-free vehicles, by line" },
    knownShare: { ro: "dintre cursele cu marcaj cunoscut au vehicul accesibil;", en: "of trips with a known flag have a step-free vehicle;" },
    recordedTrips: { ro: "curse înregistrate în total.", en: "recorded trips in total." },
    sampleRange: { ro: "Pe oră, eșantionul are", en: "Per-hour samples contain" },
    order: {
      ro: "Primele sunt liniile cu cele mai multe curse cu vehicul marcat neaccesibil: acolo ar conta întâi un vehicul cu podea joasă.",
      en: "First come the lines with the most trips with a vehicle flagged not step-free: that is where a low-floor vehicle would count first.",
    },
    line: { ro: "Linia", en: "Line" },
    share: { ro: "Accesibil", en: "Step-free" },
    n: { ro: "Curse", en: "Trips" },
    unknownHour: { ro: "marcaj necunoscut", en: "flag unknown" },
    hours: { ro: "Pe ore, 0–23", en: "By hour, 0–23" },
    stripLabel: { ro: "Linia {line}, curse accesibile din total, pe ore:", en: "Line {line}, step-free of all trips, by hour:" },
    legend: {
      ro: "Pătrat plin: toate cursele cu marcaj cunoscut din acea oră au vehicul accesibil; gol: niciuna; gri: marcaj necunoscut; lipsă: nicio cursă înregistrată. Citiți și coloana Curse.",
      en: "Full square: every trip with a known flag that hour had a step-free vehicle; empty: none; grey: flag unknown; missing: no recorded trip. Read the Trips column too.",
    },
    all: { ro: "Arată toate liniile", en: "Show all lines" },
    fewer: { ro: "Doar primele 8", en: "Only the first 8" },
  },
};
