---
name: Rețeaua Vie
description: The back office behind CityApp. A plain working tool on a light ground, with the city's own line colours.
colors:
  background: "oklch(0.984 0.002 165)"
  foreground: "oklch(0.2 0.012 165)"
  card: "oklch(1 0 0)"
  muted: "oklch(0.96 0.004 165)"
  muted-foreground: "oklch(0.44 0.012 165)"
  border: "oklch(0.915 0.005 165)"
  primary: "oklch(0.5 0.095 166)"
  primary-foreground: "oklch(0.99 0.004 165)"
  accent: "oklch(0.95 0.025 166)"
  accent-foreground: "oklch(0.32 0.06 166)"
  closure: "oklch(0.6 0.2 27)"
  closure-ink: "oklch(0.5 0.17 27)"
  closure-soft: "oklch(0.965 0.025 25)"
  line-tram: "#e3a900"
  line-trolley: "#6f2095"
  line-bus: "#4d897f"
  line-express: "#f58134"
  line-metropolitan: "#0148a2"
typography:
  page-title:
    fontFamily: "Onest Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.015em"
  lead:
    fontFamily: "Onest Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.05rem"
    fontWeight: 500
    lineHeight: 1.375
  section-title:
    fontFamily: "Onest Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "Onest Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
  action:
    fontFamily: "Onest Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.375
  micro:
    fontFamily: "Onest Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 500
    lineHeight: 1.3
  number:
    fontFamily: "Onest Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.015em"
  note:
    fontFamily: "Onest Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  sm: "0.375rem"
  md: "0.5rem"
  lg: "0.75rem"
  xl: "1rem"
  full: "9999px"
spacing:
  row: "0.625rem"
  gutter: "1.5rem"
  section: "2rem"
  rail: "5.25rem"
  panel: "27rem"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.lg}"
    height: "2.75rem"
  button-outline:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    height: "2.5rem"
  tag-needs-person:
    backgroundColor: "{colors.closure-soft}"
    textColor: "{colors.closure-ink}"
    rounded: "{rounded.sm}"
    height: "1.5rem"
  tag-done:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-foreground}"
    rounded: "{rounded.sm}"
    height: "1.5rem"
  kind-measured:
    backgroundColor: "{colors.foreground}"
    textColor: "{colors.background}"
    rounded: "{rounded.full}"
  rail-item-current:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-foreground}"
    rounded: "{rounded.full}"
  map-label-work:
    backgroundColor: "{colors.closure-ink}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
---

# Design

## Overview

Rețeaua Vie is used at a desk by City Hall mobility staff and STPT dispatch. The app is an Operate surface: it looks like the tools they already trust (a rail, a list, a map), and the craft is in what it explains without being asked. The landing page shares the tokens and is louder; this file describes the app at `/app`.

The app has **places, not steps**. A person opens one of four:

| Place | Who stays there | What it holds |
|---|---|---|
| **Azi** | STPT dispatch, all day | What waits for a person, then the timetable against the street: live vehicles, lines with fewer trips seen than scheduled, works under way |
| **Lucrări** | City Hall, per request | Every work, and the way a new one enters (its notice, pasted). One work opens as a page with the only sequence in the product: Impact → Perioadă → Anunț → Pe teren |
| **Linii** | Both, as reference | 58 lines ordered by trips seen against the timetable; one line shows its stations in order, its vehicles and its recorded day |
| **Rapoarte** | SMTT, City Hall, monthly | Obligations, the daily trip registry, past works, indicators, public files. No map |

Layout at 1440×900: a 5.25rem rail, a 27rem panel, and the map on everything that is left. The map stays mounted between places and follows what the panel talks about. Below 768px the map sits on top, the panel under it and the rail becomes a bottom bar.

Three rules decide most questions:

1. **Nobody has to know the city.** If the panel names a stop, a street or a line, the map frames it and writes its name on it. A line is always shown as its stations in order (the line diagram), never as a bare number.
2. **A screen says what to do, or says there is nothing to do.** "Așteaptă un om" lists tasks with one verb each. A question shows its context, a proposal when we have one, and two answers.
3. **Measured and estimated never look alike.** Measured is a solid ink pill with its sample; an estimate is a dashed outline that names its model. Unknown is written "necunoscut", never zero.

## Colors

Off-white ground, near-black ink with a green cast, one green for the primary action and for "done". **Barrier red marks works and what waits for a person, and nothing else.** Transit lines always use STPT's own GTFS colours (tram gold, trolleybus purple, bus teal, express orange, metropolitan blue); never recolour a line, and never use a line colour for UI state.

On the map, with nothing selected, the whole network shows its colours at half strength. When the panel focuses on a line or a work, that line takes full colour and the rest steps back to grey.

## Typography

One family, Onest Variable, on a fixed rem scale: 20px page titles, 16.8px lead sentence, 16px for the question and the primary action, 14px body and section titles, 12px notes, 11px for rail labels and chart ticks. Numbers are tabular everywhere. Each tab opens with one lead sentence that answers its question in words ("Linia 4 nu circulă; liniile 2 și 7 circulă pe trasee scurtate."), then at most three numbers at 24px. No eyebrow labels, no uppercase tracking.

Interface language is Romanian. Counts follow Romanian grammar ("16 stații", "21 de stații").

## Layout

- Panel anatomy: a fixed head (where you are, status, the work's tabs), a body that scrolls, one action at the foot. The foot is empty while a question waits, so the answer buttons are the only action on screen.
- Sections inside a panel are separated by 2rem and titled at 14px semibold; lists are flat rows with hover, not cards. A card (border, soft shadow) is reserved for the one thing that needs an answer.
- Long runs of similar stations fold to "N stații între ele"; details fold into accordions at the end of a tab.
- The map legend lists only what is on the map at that moment, in words.

## Elevation & Depth

Flat by default: the rail and panel are separated from the map by a 1px border, not a shadow. Two soft shadows exist: `shadow-card` for the open question, popovers and map labels; nothing floats over the map except the legend, the zoom control and names.

## Shapes

Radius 0.5–0.75rem on controls and rows, 1rem on the question card, full on pills and status dots. Line badges are small rounded rectangles in the line colour. A work on the map is a thick dashed red line with a white casing; a line with no vehicle in the live data is dashed in its own colour.

## Components

- **Rail**: four labelled icons; the current one has a green pill behind the icon. Azi carries a red count of things waiting. The simulated clock sits at the bottom with the data sources behind it.
- **Task row** (Azi): leading mark (works icon or line badge), one sentence, one detail line, the owner ("STPT · dispecerat"), one verb on the right.
- **Line diagram** (`LineStrip`): stations in travel order on a track in the line colour. Terminus = ring, "nu oprește" = red cross with a dashed red track, "de hotărât" = ink ring with a dashed ink track. The word is written once per run; colour only repeats it.
- **Question card**: question, the line diagram with the asked stretch marked, the reason, the platform's proposal if any, two buttons. Answered questions collapse to one line with a green check and can be reopened.
- **Work tabs**: numbered 1–4 because the order is real; a number turns into a green check when that part is done.
- **Recorded data**: `SeenBar` (trips seen in ink, unseen in red), `HourBars` (outline = timetable, fill = seen), `PunctualityBar`. Each carries the recording span and the caveat text from the API.
- **Replay** (`Replay.tsx`): a quiet button ("Redă sâmbătă dimineață") on Azi and on a line's page. While it is on, a bar sits over the map: play or pause, the recorded minute, a slider over the whole window, and "Înapoi la acum". The vehicles on the map are then the ones in that recorded frame, nothing is interpolated or invented, the legend says "vehicul, din înregistrare", and a line with no vehicle that day stays dashed. On a line's page the bar also counts that line's vehicles ("linia 23: niciunul în tot intervalul"). `?redare` in the address opens a page with the replay running.
- **New work** (`/app/lucrari/nou`): one textarea for the notice, then what the platform read (period, lines, street drawn on the map, the sentences it could not use) before anything is computed. A notice that was read and left is a draft ("Ciornă") in Lucrări and a task on Azi.
- **Map labels**: white chip for a stop, red chip for a work, dashed chip for a line without vehicle. Two labels near each other go above and below their points. A work's chip moves to another side of its point when it would cover a stop or a stop's name.

## Do's and Don'ts

- Do write the place name on the map whenever the panel mentions it.
- Do say "fără vehicul în datele live" and "nevăzute în datele live"; never "nu a circulat", "cursă neefectuată" or anything that assigns blame.
- Do keep one solid green button per screen.
- Don't add a fifth place to the rail; a new feature belongs to a work, a line or a report.
- Don't show a measured number without its recording span, or an estimate without its model.
- Don't use red for decoration, or line colours for status.
- Don't animate to decorate: vehicles glide to their new position, the map flies to what the panel names, and nothing else moves. Reduced motion turns both into jumps, and the replay then waits for the play button.
- Don't show recorded vehicles without the word "înregistrare" and the recorded time beside them; live and recorded must never be mistaken for each other.
