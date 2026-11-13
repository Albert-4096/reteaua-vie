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
