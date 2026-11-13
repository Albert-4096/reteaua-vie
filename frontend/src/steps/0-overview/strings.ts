// Step 0 text, Romanian first. Rendered with tr() so the language switch applies.
export const S = {
  title: { ro: "Cum stă rețeaua azi?", en: "How is the network today?" },
  sentence: (at: string) => ({
    ro: `Situația la ${at}: lucrările publicate active și ce pierde rețeaua din cauza lor.`,
    en: `As of ${at}: the published closures in force and what the network loses because of them.`,
  }),
  figClosures: { ro: "lucrări active", en: "active closures" },
  figGhost: { ro: "plecări pierdute azi", en: "departures lost today" },
  figVehicles: (at: string) => ({ ro: `vehicule · înregistrare ${at}`, en: `vehicles · recording ${at}` }),
  list: { ro: "Lucrări active", en: "Active closures" },
  none: { ro: "Nicio lucrare publicată nu e activă acum.", en: "No published closure is in force now." },
  plan: { ro: "Planifică o lucrare", en: "Plan a closure" },
  layers: { ro: "Straturi pe hartă", en: "Map layers" },
  layer: {
    network: { ro: "Rețeaua de transport public", en: "Public transport network" },
    closures: { ro: "Lucrările active", en: "Active closures" },
    bike: { ro: "Piste de biciclete (OpenStreetMap)", en: "Bike lanes (OpenStreetMap)" },
    parking: { ro: "Parcări Timpark", en: "Timpark parking" },
    population: { ro: "Populație (estimare, GHSL 2020)", en: "Population (estimate, GHSL 2020)" },
  },
  compliance: { ro: "Obligații UE acoperite de exporturile noastre", en: "EU obligations our exports cover" },
  covered: { ro: "acoperite", en: "covered" },
  partial: { ro: "parțial", en: "partly" },
  missing: { ro: "lipsă", en: "missing" },
  upcoming: { ro: "Încep în următoarele 7 zile", en: "Starting in the next 7 days" },
};
