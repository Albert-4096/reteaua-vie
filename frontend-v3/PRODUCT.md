# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Rețeaua Vie is designed first for the people who do the back-office work of public transport in Timișoara, on a laptop or desktop screen:

- **City Hall mobility staff** (Direcția de mobilitate, Comisia de circulație): they approve works that close a street and need to see, before signing, which lines, stops and residents lose service.
- **STPT** (the operator): dispatch, and passenger information, which today writes each notice by hand for each channel.
- **SMTT** (the association that pays STPT on its monthly report): a reader of the monitoring and compliance outputs.

Citizens never open Rețeaua Vie. They see its results through Timisoara CityApp (the City Hall's official app), Google and other GTFS-RT readers, the stop poster with its QR code, and stop displays. Any rider screen appears only as a labelled CityApp mock fed by the real API.

The UniHack 8 jury (judging Sun 15 Nov 2026) evaluates it as this staff tool. The screens are not tuned for the pitch at the cost of the staff's work.

## Product Purpose

The published timetable is the network on paper. Rețeaua Vie is the network on the street: it compares the timetable with street works and with the vehicles in the City Hall's live data. Where the two differ, the City Hall decides on numbers, and CityApp, Google and the stop poster receive the same alert.

The app is organised by what people open it for, not by a tour. Four places: **Azi** (what waits for a person, and the timetable against the street right now; where STPT dispatch stays), **Lucrări** (every work; one work is the only sequence: *Impact* who loses service → *Perioadă* when it hurts least → *Anunț* what riders learn → *Pe teren* what vehicles actually did; where the City Hall decides), **Linii** (each line with its stations in order, its vehicles and its recorded day) and **Rapoarte** (obligations, the daily trip registry, public files; opened monthly). Three verbs: it sees (Vede), helps decide (Decide), announces (Anunță).

Success metric: phantom departures (*plecări-fantomă*), meaning departures the published timetable lists that do not run, either because works suspend the stop or because the trip has no vehicle in the live data. Success means each one becomes an announced change.

After the hackathon it is a hand-over: the City Hall and STPT can run it without the team. Future work must keep it adoptable.

## Positioning

The back office behind CityApp, not a competitor to it: "CityApp is what the citizen sees. Rețeaua Vie is what sits behind it: the data, the calculation and the decision."

What a neighbouring product cannot truthfully copy: it runs only on data the city already publishes (the SMTT GTFS timetable, the City Hall's live vehicle endpoint recorded every 15 s, STPT notices, works permits, Timpark, citizen reports), on one server, under the MIT licence, with no paid key. A person confirms before anything reaches a citizen, and each output has a named owner.

## Operating Context

- Used at a desk, on laptop and PC screens (designed at 1440×900), in a working day of approving works and publishing notices.
- Demo state: a simulated clock, Sunday 8 Nov 2026, 12:00, the day of the Bd. 16 Decembrie 1989 tram works. Live vehicles on the map are real and current. The simulation is always labelled.
- Outputs leave as standard files: GTFS-RT ServiceAlerts, DATEX II, NGSI-LD, metadata for the National Access Point (NAP), an A4 stop poster with QR code and audio version, and neighbourhood notices. CityApp, Google and the NAP *can* read them; we never claim they already do.
- SMTT pays STPT monthly on STPT's own report, from kilometres and trips (Contract 1812/2020). The platform gives an independent check from the City Hall's live data. It never computes a sum in lei.

## Capabilities and Constraints

- **Built and live (unihack.alberyt.xyz):** four places beside one shared map (Azi, Lucrări, Linii, Rapoarte; see DESIGN.md). Closure impact (lines, stops, departures lost, residents beyond 400 m, GHSL 2020 model), the questions a person must answer about unclear stops, the window with least impact, conflicts between works, publish to all channels, lines with scheduled trips but no vehicle in the live data, measured detour effect, and the compliance report with public files. Modules for bikes (M5) and parking (M6) stay built (all-in-one platform).
- **No mock data.** What cannot be computed is `null` ("necunoscut"). No number appears in the UI without a source in the evaluation (`eval/results/latest.json`, README §7) or our own measurement.
- **Human in the loop.** A detected "line without vehicle" reaches CityApp only after a person confirms it. We never send GTFS-RT `CANCELED`: we infer, we do not know.
- **Interface language: Romanian only.** The API carries Romanian and English text (`{ ro, en }`), and the README is bilingual. The app screens stay Romanian.
- **Terminology (binding):** say "curse fără vehicul în datele live", never "curse neefectuate" or "din culpa operatorului" (SMTT classifies trips). Every number is either "Măsurat" (with its sample) or "Estimare" (with its model), and the two never look alike.
- **Undecided:** phone validation of student passes (NFC/QR check-in) is a vision item, not built.

## Brand Commitments

- Name: **Rețeaua Vie**. The logo is owned by Erol. Do not redesign it.
- Transit lines always appear in STPT's own GTFS route colours.
- Never show a logo strip that implies the City Hall, STPT or anyone else is a client.
- Voice: plain, factual Romanian. Statements are the safe formulations (e.g. "orarul publicat le listează", not "aplicațiile le arată"; never "CityApp greșește" or "STPT n-a circulat").

## Evidence on Hand

- Hero case: works on Bd. 16 Decembrie 1989, 8 Nov 2026. Secondary cases: Str. Ardealului (E3) and Piața Mocioni (measured detour).
- Evaluation of the closure analysis on 5 real STPT notices: `make eval`, results in `eval/results/latest.json`, summarised in README §7.
- Line 23, Sat 14 Nov 2026 morning: 19 scheduled trips between 06:00 and 10:41 and no vehicle of the line in the City Hall's live data (prepared case `case_l23`, recorded by us).
- Accessibility: one axe-core run on 14 Nov 2026 (steps 0–5 and the QR stop page, at 375 and 1440 px, default states) found 0 violations. It is not a WCAG audit.
- **Absent, never to be fabricated:** customers, pilots or adoption by the City Hall, STPT, CityApp or Google; testimonials; any money figure in lei for line 23 or for unvalidated trips; a claim that EU Reg. 2024/490 already binds Timișoara.

## Product Principles

1. **Back office, never a rider app.** Citizens get the result through the channels they already use.
2. **Every feature names two gains:** a direct one for the City Hall, STPT or SMTT (money, staff time, evidence for contract payments, compliance) and one for citizens. If we cannot say it in a sentence, it does not get built.
3. **Real data, honest labels.** Measured and estimated look different, unknown stays unknown, simulation is labelled.
4. **A person decides; the platform prepares.** Recommendations are marked as ours; nothing reaches a citizen without a human confirmation.
5. **Keep it simple.** Everything has one place. A screen says what to do, or that there is nothing to do: one question, its answer as a sentence, details folded, one next action. Nothing is removed from the product, and nothing new opens in a default view.
6. **Nobody has to know the city.** A stop, street or line named in a panel is framed and named on the map, and a line is shown as its stations in order.
7. **The recording is the proof.** Where we have measured vehicles (the City Hall live feed, kept every 15 s), the measured number is shown next to the timetable one, with its recording span.

## Accessibility & Inclusion

Keep the app at zero axe-core violations (WCAG 2.0/2.1 A and AA rules) at 375 and 1440 px. Every map has a text equivalent in the panel. The stop poster has an audio version for riders who cannot read it. Respect reduced motion. The European Accessibility Act applies in Romania through Law 232/2022. Whether Directive 2016/2102 binds this tool is unverified.
