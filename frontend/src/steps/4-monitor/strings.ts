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
  // O2, prepared case case_l23: lines with no vehicle in the live data (never „cursă neefectuată”).
  missing: {
    title: { ro: "Linii fără vehicul în datele live", en: "Lines with no vehicle in the live data" },
    sentence: (when: string) => ({
      ro: `${when}. Din datele live ale Primăriei, înregistrate de noi; neconfirmat de STPT.`,
      en: `${when}. From the City Hall's live data, recorded by us; not confirmed by STPT.`,
    }),
    figNone: { ro: "linii fără vehicul", en: "lines with no vehicle" },
    figPartial: { ro: "linii parțial (unele curse nevăzute)", en: "lines partly seen (some trips not seen)" },
    figHealthy: { ro: "din minute cu date bune", en: "of minutes with good data" },
    incomplete: {
      ro: "Înregistrare incompletă (sub 80% din minute cu date bune): nu marcăm nicio linie.",
      en: "Incomplete recording (under 80% of minutes with good data): we flag no line.",
    },
    empty: { ro: "Nicio linie marcată în această fereastră.", en: "No line flagged in this window." },
    list: { ro: "Liniile marcate", en: "Flagged lines" },
    line: (n: string) => ({ ro: `Linia ${n}`, en: `Line ${n}` }),
    none: {
      ro: "fără vehicul în datele live (neconfirmat de STPT)",
      en: "no vehicle in the live data (not confirmed by STPT)",
    },
    partial: { ro: "parțial: unele curse nevăzute", en: "partly: some trips not seen" },
    since: (t: string) => ({ ro: `din ${t}`, en: `since ${t}` }),
    seen: { ro: "curse văzute din", en: "trips seen of" },
    inService: { ro: "în orar", en: "scheduled" },
    lastSeen: (t: string) => ({ ro: `văzută ultima dată ${t}`, en: `last seen ${t}` }),
    neverSeen: { ro: "nicio apariție", en: "never seen" },
    firstMissed: { ro: "Prima cursă fără vehicul", en: "First trip with no vehicle" },
    byMode: { ro: "Curse fără vehicul în datele live, pe mod", en: "Trips with no vehicle in the live data, by mode" },
    of: { ro: "din", en: "of" },
    mode: {
      autobuz: { ro: "autobuz", en: "bus" },
      troleibuz: { ro: "troleibuz", en: "trolleybus" },
      tramvai: { ro: "tramvai", en: "tram" },
    } as Record<string, { ro: string; en: string }>,
    recording: { ro: "instantanee înregistrate, dintre care bune", en: "snapshots recorded, of which good" },
    mapStops: (names: string) => ({
      ro: `prima stație fără vehicul: ${names}`,
      en: `first stop with no vehicle: ${names}`,
    }),
  },
};
