// Step 2 text, Romanian first. Rendered with tr() so the language switch applies.
export const S = {
  title: { ro: "Care variantă? Când?", en: "Which option? When?" },
  sentence: (hours: number) => ({
    ro: `Perioadele de ${hours} ore cu cele mai puține plecări pierdute și cele două variante pregătite.`,
    en: `The ${hours}-hour windows with the fewest departures lost and the two prepared options.`,
  }),
  windows: { ro: "Când strică cel mai puțin", en: "When it does the least harm" },
  window: { ro: "Perioada", en: "Window" },
  lost: { ro: "Plecări pierdute", en: "Departures lost" },
  noticeWindow: { ro: "perioada din anunț", en: "the notice's window" },
  compare: { ro: "Variantele pregătite", en: "The prepared options" },
  rowLost: { ro: "Plecări pierdute", en: "Departures lost" },
  rowStop: { ro: "Locuitori fără stație la 400 m", en: "Residents with no stop within 400 m" },
  rowAccess: { ro: "Locuitori fără spital în 30 min (estimare)", en: "Residents with no hospital within 30 min (estimate)" },
  noScenarios: { ro: "Lucrarea nu are încă două variante pregătite.", en: "This closure has no two prepared options yet." },
  confirm: { ro: "Confirmă", en: "Confirm" },
  moreWindows: { ro: "Celelalte perioade", en: "The other windows" },
  method: { ro: "Cum sunt ordonate", en: "How they are ranked" },
  notes: { ro: "Ce schimbă fiecare variantă", en: "What each option changes" },
  whatIf: { ro: "Ce dacă rămâne închisă?", en: "What if it stays closed?" },
  whatIfText: {
    ro: "O stradă închisă nu mută tot traficul pe străzile vecine. În peste 70 de cazuri din 11 țări, după ce spațiul pentru mașini a fost redus, o parte din trafic nu a mai apărut pe străzile din jur (Cairns, Atkins, Goodwin 2002). Lucrarea poate fi și un test pentru o stradă pietonală sau o bandă de autobuz. Nu avem o cifră pentru Timișoara.",
    en: "A closed street does not move all its traffic to the streets around it. In over 70 cases from 11 countries, after road space for cars was reduced, part of the traffic did not reappear on nearby streets (Cairns, Atkins, Goodwin 2002). The works can also be a trial for a pedestrian street or a bus lane. We have no figure for Timișoara.",
  },
};

// N1: the one-page approval file for the traffic commission (printed with Ctrl+P or the print button).
export const A = {
  print: { ro: "Tipărește dosarul", en: "Print the file" },
  printHint: {
    ro: "O pagină A4 pentru Comisia de circulație, cu sursa fiecărei cifre.",
    en: "One A4 page for the traffic commission, with the source of every number.",
  },
  title: { ro: "Dosar pentru Comisia de circulație", en: "File for the traffic commission" },
  printedAt: (when: string, id: string) => ({
    ro: `Tipărit din Rețeaua Vie la ${when} · lucrarea ${id}`,
    en: `Printed from Rețeaua Vie on ${when} · closure ${id}`,
  }),
  works: { ro: "Lucrarea", en: "The works" },
  where: { ro: "Unde", en: "Where" },
  when: { ro: "Perioada cerută", en: "Requested window" },
  notice: { ro: "Anunțul sursă", en: "Source notice" },
  lines: { ro: "Ce se schimbă la linii", en: "What changes for the lines" },
  action: {
    suspended: { ro: "suspendată", en: "suspended" },
    shortened: { ro: "scurtată", en: "shortened" },
    rerouted: { ro: "deviată", en: "rerouted" },
  } as Record<string, { ro: string; en: string }>,
  line: (n: string) => ({ ro: `linia ${n}`, en: `line ${n}` }),
  dir: (d: number) => ({ ro: `sensul ${d + 1}`, en: `direction ${d + 1}` }),
  tempRoute: (n: string, streets: string) => ({
    ro: `linie temporară ${n}: ${streets}`,
    en: `temporary line ${n}: ${streets}`,
  }),
  undecided: (n: number) => ({
    ro: `Atenție: ${n} rânduri neclare nu au încă răspuns (pasul 1). Cifrele de mai jos nu le numără.`,
    en: `Note: ${n} unsure rows have no answer yet (step 1). The figures below do not count them.`,
  }),
  loss: { ro: "Ce pierd oamenii, în perioada cerută", en: "What people lose, in the requested window" },
  departures: { ro: "Plecări pierdute", en: "Departures lost" },
  residents: { ro: "Locuitori fără stație la 400 m", en: "Residents with no stop within 400 m" },
  suspended: { ro: "Stații fără niciun mijloc de transport", en: "Stops with no service at all" },
  routes: { ro: "Linii afectate", en: "Lines affected" },
  stops: { ro: "Stațiile pierdute, pe linii", en: "Stops lost, by line" },
  stopsNone: { ro: "Nicio stație pierdută.", en: "No stop lost." },
  stopsLine: (n: string, count: number) => ({
    ro: `Linia ${n} · ${count} ${count === 1 ? "stație" : "stații"}`,
    en: `Line ${n} · ${count} ${count === 1 ? "stop" : "stops"}`,
  }),
  departuresShort: { ro: "plecări", en: "departures" },
  window: { ro: "Perioada", en: "The window" },
  windowNotice: { ro: "Din anunț", en: "From the notice" },
  windowBest: (h: number) => ({
    ro: `Cea mai bună perioadă de ${h} ore găsită`,
    en: `Best ${h}-hour window found`,
  }),
  windowPending: { ro: "încă se calculează", en: "still being computed" },
  conflicts: { ro: "Conflicte cu alte lucrări", en: "Conflicts with other works" },
  conflictsNone: { ro: "Niciun conflict cu lucrările din registru.", en: "No conflict with the works in the register." },
  kind: {
    same_corridor: { ro: "același coridor", en: "same corridor" },
    shared_detour: { ro: "aceeași ocolire", en: "same detour" },
    same_stops: { ro: "aceleași stații", en: "same stops" },
  } as Record<string, { ro: string; en: string }>,
  linesShort: { ro: "linii", en: "lines" },
  decisions: { ro: "Ce a decis un om (pasul 1)", en: "What a person decided (step 1)" },
  certain: (n: number) => ({
    ro: `${n} rânduri sigure din anunț și orar, fără întrebare.`,
    en: `${n} certain rows from the notice and the timetable, no question asked.`,
  }),
  overridden: (n: number) => ({
    ro: `${n} dintre ele schimbate de om.`,
    en: `${n} of them changed by a person.`,
  }),
  answer: {
    open: { ro: "fără răspuns", en: "no answer" },
    lost: { ro: "răspuns: nu oprește", en: "answer: does not stop" },
    served: { ro: "răspuns: oprește", en: "answer: stops" },
    mixed: { ro: "răspuns pe rânduri", en: "answered row by row" },
  } as Record<string, { ro: string; en: string }>,
  rows: (lost: number, served: number, open: number) => ({
    ro: `${lost} nu oprește · ${served} oprește · ${open} fără răspuns`,
    en: `${lost} does not stop · ${served} stops · ${open} no answer`,
  }),
  noQuestions: { ro: "Nicio întrebare: toate rândurile erau sigure.", en: "No question: every row was certain." },
  sources: { ro: "Surse (numerele dintre paranteze)", en: "Sources (the numbers in brackets)" },
  method: { ro: "Cum se calculează", en: "How it is computed" },
  fetched: (d: string) => ({ ro: `date din ${d}`, en: `data of ${d}` }),
  verdict: { ro: "Decizia Comisiei", en: "The commission's decision" },
  approveNotice: { ro: "Aprobat, perioada din anunț", en: "Approved, the notice's window" },
  approveBest: { ro: "Aprobat, perioada propusă", en: "Approved, the proposed window" },
  reject: { ro: "Respins", en: "Rejected" },
  signature: { ro: "Semnătura", en: "Signature" },
  date: { ro: "Data", en: "Date" },
};

// R5: km not run on the cut section and the walk between its ends, for SMTT. Km only, never money.
export const K = {
  title: { ro: "Km nefăcuți, pentru SMTT", en: "Km not run, for SMTT" },
  mode: {
    tram: { ro: "Tramvai", en: "Tram" },
    bus: { ro: "Autobuz", en: "Bus" },
    trolleybus: { ro: "Troleibuz", en: "Trolleybus" },
  } as Record<string, { ro: string; en: string }>,
  trips: { ro: "curse", en: "trips" },
  perTrip: { ro: "km nefăcuți", en: "km not run" },
  walk: { ro: "pe jos între capete", en: "on foot between the ends" },
  none: { ro: "Nicio linie nu pierde o porțiune de traseu.", en: "No line loses part of its route." },
  source: (v: string) => ({
    ro: `Din orarul GTFS SMTT ${v}, pentru perioada din anunț. Doar km, fără costuri.`,
    en: `From the SMTT GTFS timetable ${v}, for the notice's window. Km only, no costs.`,
  }),
  methodKm: {
    ro: "Lungimea traseului GTFS între prima și ultima stație lipsă × cursele din fereastră, pe fiecare sens; km pe cursă = totalul ÷ curse.",
    en: "Length of the GTFS route between the first and the last lost stop × the trips in the window, per direction; km per trip = the total ÷ trips.",
  },
  methodWalk: {
    ro: "Distanța pe jos (OSM) între ultima stație servită înainte de porțiunea închisă și prima de după, la 80 m/min.",
    en: "Walking distance (OSM) between the last served stop before the closed section and the first one after it, at 80 m/min.",
  },
  csv: { ro: "Km nefăcuți pe linii, pentru SMTT (CSV)", en: "Km not run per line, for SMTT (CSV)" },
  csvHint: {
    ro: "Câți km din orar nu se fac pe fiecare linie și sens în perioada lucrării, ca SMTT să verifice raportul lunar al STPT.",
    en: "How many timetabled km each line and direction does not run during the works, for SMTT to check STPT's monthly report.",
  },
};
