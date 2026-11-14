// Step 3 text, Romanian first. Rendered with tr() so the language switch applies.
export const S = {
  qrAlt: { ro: "Codul QR de pe afișul stației", en: "The QR code on the stop poster" },
  qrHint: {
    ro: "Scanați cu camera telefonului. Se deschide alerta acestei stații, cu text și audio.",
    en: "Scan with your phone camera. It opens this stop's alert, with text and audio.",
  },
  qrPhoneOpen: { ro: "Arată pagina de pe telefon", en: "Show the phone page" },
  qrPhoneTitle: { ro: "Pagina din codul QR, pe telefon", en: "The page behind the QR code, on a phone" },
  qrPhoneClose: { ro: "Închide", en: "Close" },
  feedsTab: { ro: "Ce primește CityApp", en: "What CityApp gets" },
  feedsTitle: { ro: "Ce primește CityApp", en: "What CityApp gets" },
  feedsSentence: {
    ro: "Fișierele publice pe care CityApp, Google și platforma orașului le pot citi azi. Se schimbă la fiecare publicare.",
    en: "The public files CityApp, Google and the city platform can read today. They change with every publish.",
  },
  feeds: {
    alertsPb: {
      ro: "Google Maps și CityApp: alerta lângă plecările liniei din stația închisă (GTFS-RT, formatul standard).",
      en: "Google Maps and CityApp: the alert next to the line's departures at the closed stop (GTFS-RT, the standard format).",
    },
    alertsJson: {
      ro: "Același flux, ușor de citit: cardul stației din CityApp, ca în macheta de la „În aplicații”.",
      en: "The same feed, easy to read: the stop card in CityApp, as in the mock-up under „In apps”.",
    },
    ngsi: {
      ro: "Platforma de date a orașului (FIWARE NGSI-LD): fiecare alertă, legată de stația ei.",
      en: "The city's data platform (FIWARE NGSI-LD): each alert, linked to its stop.",
    },
    notices: {
      ro: "CityApp, la cartierul ales: lucrările din cartier, în ce stații nu opresc liniile și ce linii le deservesc încă.",
      en: "CityApp, for the chosen neighbourhood: the works there, the stops where lines do not stop and the lines that still serve them.",
    },
    route: {
      ro: "CityApp, când cineva caută un drum: un traseu care ocolește stațiile suspendate (exemplu: de la stația 907 la Piața Victoriei).",
      en: "CityApp, when someone looks for a trip: a route that avoids the suspended stops (example: from stop 907 to Piața Victoriei).",
    },
    stopStatus: {
      ro: "Starea unei stații: CityApp, când cineva atinge o stație. De ce nu opresc liniile, stația deservită cea mai apropiată și sursa, în română și engleză (exemplu: stația 907, Calea Torontalului).",
      en: "Stop status: CityApp, when someone taps a stop. Why the lines do not stop, the nearest served stop and the source, in Romanian and English (example: stop 907, Calea Torontalului).",
    },
    datex: {
      ro: "Hărțile de navigație rutieră: strada închisă și perioada (DATEX II).",
      en: "Road navigation maps: the closed street and the window (DATEX II).",
    },
  },
  // R3-F: the Timi row; {{n}} is filled from /api/tools.json.
  timi: {
    all: { ro: "Pentru Timi: tools.json ({{n}} funcții, doar citire).", en: "For Timi: tools.json ({{n}} functions, read-only)." },
    some: {
      ro: "Pentru Timi: tools.json ({{n}} din {{total}} funcții active, doar citire).",
      en: "For Timi: tools.json ({{n}} of {{total}} functions live, read-only).",
    },
    where: {
      ro: "Asistentul Primăriei le poate apela ca să răspundă „de ce nu vine linia 4?” din datele confirmate, la fel ca anunțul publicat.",
      en: "The City Hall's assistant can call them to answer „why is line 4 not coming?” from confirmed data, matching the published notice.",
    },
  },
  // S1-F: the stop status answer inside the CityApp mock-up.
  stopStatus: {
    label: { ro: "Starea stației", en: "Stop status" },
    source: { ro: "Sursa", en: "Source" },
    noStop: { ro: "nu oprește", en: "does not stop" },
    noVehicle: { ro: "niciun vehicul în datele live (neconfirmat de STPT)", en: "no vehicle in live data (not confirmed by STPT)" },
    unconfirmed: { ro: "de confirmat", en: "to be confirmed" },
    stepFree: {
      ro: "Vehicul accesibil: așteptare tipică după înregistrare",
      en: "Step-free vehicle: typical wait from our recording",
    },
    action: {
      suspended: { ro: "suspendată", en: "suspended" },
      shortened: { ro: "scurtată", en: "shortened" },
      rerouted: { ro: "deviată", en: "rerouted" },
    },
  },
};
