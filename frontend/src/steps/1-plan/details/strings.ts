// Text of the step-1 detail tabs, Romanian first. Rendered with tr() so the language switch applies.
export const S = {
  tabs: { ro: "Alte efecte ale lucrării", en: "Other effects of the closure" },
  tab: {
    bike: { ro: "Biciclete", en: "Bikes" },
    parking: { ro: "Parcări", en: "Parking" },
    access: { ro: "Acces", en: "Access" },
    detour: { ro: "Ocolire", en: "Detour" },
    conflicts: { ro: "Conflicte", en: "Conflicts" },
    reports: { ro: "Sesizări", en: "Reports" },
  },
  bikeLanes: { ro: "de pistă de biciclete în zona lucrării", en: "of bike lane inside the closure area" },
  bikeParking: { ro: "parcări de biciclete în zona lucrării", en: "bike parkings inside the closure area" },
  parkingStreets: { ro: "străzi și parcări Timpark în zona lucrării", en: "Timpark streets and lots inside the closure area" },
  accessFig: { ro: "locuitori care nu mai ajung la un spital în 30 de minute", en: "residents who no longer reach a hospital within 30 minutes" },
  estimate: { ro: "estimare", en: "estimate" },
  accessZones: { ro: "Cartierele afectate", en: "Neighbourhoods affected" },
  accessNone: { ro: "Niciun cartier nu pierde accesul.", en: "No neighbourhood loses access." },
  accessError: { ro: "estimare indisponibilă", en: "estimate unavailable" },
  detourLines: { ro: "Linii cu risc de încetinire", en: "Lines at risk of slowing down" },
  detourStreets: { ro: "Străzile pe care se mută ocolirea", en: "Streets the detour moves to" },
  detourNone: { ro: "Nicio linie cu risc de încetinire.", en: "No line at risk of slowing down." },
  conflictsNone: { ro: "Nicio altă lucrare în aceeași perioadă și zonă.", en: "No other closure in the same period and area." },
  kind: {
    same_stops: { ro: "aceleași stații", en: "same stops" },
    same_corridor: { ro: "același coridor", en: "same corridor" },
    shared_detour: { ro: "aceeași ocolire", en: "same detour" },
  } as Record<string, { ro: string; en: string }>,
  reportsFig: (r: number) => ({
    ro: `sesizări la cel mult ${r} m de lucrare`,
    en: `reports within ${r} m of the closure`,
  }),
  reportsNone: { ro: "Nicio sesizare în perioada aceasta.", en: "No report in this period." },
  reportsUncovered: (w: string) => ({
    ro: `Înregistrarea noastră de sesizări nu acoperă perioada ${w}.`,
    en: `Our recording of reports does not cover ${w}.`,
  }),
  reportsCovered: (w: string) => ({ ro: `Acoperă ${w}.`, en: `It covers ${w}.` }),
};
