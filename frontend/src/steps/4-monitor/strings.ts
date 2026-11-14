// Step 4 text, Romanian first. Rendered with tr() so the language switch applies.
export const S = {
  title: { ro: "Se respectă devierea?", en: "Is the diversion followed?" },
  sentence: (title: string, from: string, to: string) => ({
    ro: `${title}. Trecerile vehiculelor pe lângă stațiile suspendate, înregistrare ${from} – ${to}.`,
    en: `${title}. Vehicle passes by the suspended stops, recording ${from} – ${to}.`,
  }),
  noRecording: {
    ro: "Nu avem o înregistrare a vehiculelor pentru perioada acestei lucrări.",
    en: "We have no vehicle recording for this closure's window.",
  },
  figSkipped: { ro: "treceri fără oprire (sărite)", en: "passes without stopping (skipped)" },
  figServed: { ro: "treceri cu oprire (deservite)", en: "passes with a stop (served)" },
  figUnknown: { ro: "treceri necunoscute", en: "passes unknown" },
  list: { ro: "Stațiile suspendate", en: "The suspended stops" },
  skipped: { ro: "sărită", en: "skipped" },
  served: { ro: "deservită", en: "served" },
  unknown: { ro: "necunoscut", en: "unknown" },
  vehicles: (at: string) => ({
    ro: `vehicule ale acestor linii pe hartă, înregistrare ${at}`,
    en: `vehicles of these lines on the map, recording ${at}`,
  }),
  mapStops: (n: { skipped: number; served: number; unknown: number }) => ({
    ro: `stații suspendate: ${n.skipped} sărite de vehicule, ${n.served} unde un vehicul a oprit, ${n.unknown} fără treceri văzute`,
    en: `suspended stops: ${n.skipped} skipped by vehicles, ${n.served} where a vehicle stopped, ${n.unknown} with no pass seen`,
  }),
  next: { ro: "Mergi la raportare", en: "Go to reporting" },
  method: { ro: "Cum verificăm", en: "How we check" },
  seen: { ro: "vehicule văzute", en: "vehicles seen" },
  scans: { ro: "Afișe deschise:", en: "Posters opened:" },
  scansHint: {
    ro: "deschideri ale paginii QR de pe afișe, nu persoane unice",
    en: "openings of the posters' QR page, not unique people",
  },
  scansByStop: { ro: "Deschideri pe stație", en: "Openings per stop" },
};
