# Eval: how well does M1 read a real STPT notice?

We measure the disruption engine (M1) on five real notices that STPT (Societatea de Transport Public Timișoara) published on stpt.ro in October and November 2026, against a hand-made answer key.

| Post | Date | What it says | Gold rows suspended | Uncertain (not scored) |
|---|---|---|---|---|
| 11067 | 6 Nov | Tram works on Bd. 16 Decembrie 1989, 8 Nov 10:00–18:00: line 4 suspended, lines 2 and 7 shortened, temporary bus 4b | 88 | 29 |
| 11065 | 5 Nov | Str. Ardealului closed 7–12 Nov: E3 rerouted, 6 + 5 stops suspended | 11 | 0 |
| 11060 | 30 Oct | Metropolitan lines M32, M36, M37, M38, M46 and M51 diverted around Piața Mocioni | 0 | 1 |
| 11062 | 3 Nov | E3 detour after the Polonă bridge closure; no stop named | 0 | 0 |
| 11058 | 30 Oct | Timetable changes and route extensions; nothing is suspended | 0 | 0 |

A row is one (stop id, route id, direction id), which is also how the API reports affected stops. A stop served by three affected lines gives three rows.

## How the labels were made

**AI-assisted from the notice text; human review pending.** Every label file says so in `labelledBy`. A team member reviews them before any number from this folder is shown.

- `make_labels.py` holds what we read in each notice: the lines, the direction („către Elba” → the GTFS headsign), the action (`suspended` / `shortened` / `rerouted`) and the stop names as the notice writes them.
- Each name is matched to a GTFS stop id **on that line's own stop pattern**. In GTFS 4.31, 306 of the 569 stop names belong to more than one stop id, usually one per direction, so a citywide name search picks the wrong stop. The match goes in this order: exact, then without diacritics and punctuation („Canton CFR” = „Canton C.F.R.”, „Buclă” = „Bucla”), then the name without the street in parentheses. A few names need a manual match; they are marked `"match": "manual"`. Every match is kept in the label file under `resolved`, so a reviewer can check it.
- Each stop of each affected line and direction lands in exactly one list: `suspendedStopIds`, `keptStopIds` or `uncertainStopIds`. Where the notice is not clear, the stop goes to `uncertainStopIds` and the reason goes into `notes`. We do not guess.
- The labels are checked against SMTT GTFS 4.31 (valid 5 Nov to 31 Dec 2026). The feed version and its SHA-256 are in every label file.

Two things the labels show about the data:
- **GTFS 4.31 already contains the diversions of 11060 (Mocioni) and 11062 (Polonă bridge).** Every stop that notice 11060 says is served is already on the GTFS pattern, and E3 no longer stops on Str. Polonă. Measured against this feed, those notices suspend no stop, and the stops served before the diversion are not in the feed. So these two notices test whether the pipeline avoids false alarms, not whether it finds stops.
- **11067, line 7:** the notice gives only the ends („Depou Dâmbovița – Gara de Nord”). Two tram paths fit, so the middle of the line is labelled uncertain.

## The E3 figure (SPEC 5.2)

`e3_departures.py` counts the scheduled E3 departures per weekday at the stops notice 11065 suspends, straight from the GTFS (`calendar.txt` + `calendar_dates.txt`). It counts departures only, not the arrival at the last stop. Times past 24:00 count on the next calendar day (Europe/Bucharest).

Result on GTFS 4.31: **253 departures per weekday** (138 towards Elba at 6 stops, 115 towards Apicultorilor at 5 stops). The figure is the same on every weekday of the closure (Mon 9 to Thu 12 Nov 2026, service `S_AB_E3_WDSC`). E3 runs 23 trips each way on a weekday, and no other line uses these 11 stop ids. The output is in `results/e3_departures.json`.

## Run

The data lives outside the repo. Point `DATA_DIR` at it; the newest GTFS zip in `$DATA_DIR/live/gtfs/` is used.

```sh
# labels and the E3 figure (only pandas is needed)
DATA_DIR=/path/to/data uv run --no-project --with pandas python eval/make_labels.py
DATA_DIR=/path/to/data uv run --no-project --with pandas python eval/e3_departures.py --write

# the full eval, with the backend environment (this is what `make eval` runs)
DATA_DIR=/path/to/data uv run --project backend python eval/run.py
```

`run.py` calls the M1 functions directly:
- the parser: `app.m1_disruption.parser.parse_notice(text)`, which returns `{closure, unread}` as `POST /api/closures/parse` does;
- the analysis: `app.m1_disruption.analysis.analyze(closure)`, which returns an `Analysis`.

To use other functions, pass `--parser module:function` and `--analyzer module:function`. If the parser is missing, `run.py` says so and exits with code 2. If only the analysis is missing, it scores the parser's `routeActions` on the GTFS patterns and records that in `scoredFrom`.

The parser gets the notice's post date as its reference day, so „de mâine” in 11062 (posted 3 Nov) reads as 4 Nov.

For the paste-to-alert time, `run.py` drives the API in-process with the app clock at the notice's post date. It parses the notice, analyzes it, confirms every row as proposed, publishes and reads `/api/feed/alerts.pb`, then runs the MobilityData GTFS-RT validator on the published feed (`gtfsRtValidatorPass`). It uses a temporary `DATA_DIR` with its own empty `state/`, so the demo state is never touched. It never loads the env file, so no LLM or text-to-speech key is used. `--no-publish` skips this step.

## Independent gold: SMTT's own timetable changes

`gold_gtfs_diff.py` needs no labels at all. It compares consecutive SMTT GTFS versions (`$DATA_DIR/gtfs-history/*.zip` and the current zip) and lists, per line and direction, the stop ids served on some trip of the older version and on no trip of the newer one. `run.py` scores the pipeline against it next to the AI-assisted labels:
- 4.29 → 4.30 (2 Nov), lines M32, M36, M37, M38, M46, M51: the Mocioni diversion (notice 11060).
- 4.29 → 4.30, lines M11, M29, M30: compared with notice 11058. The notice names the M30 extension to the UMFT campus, and the GTFS adds that stop. The GTFS also drops „Moldovei (Ghiroda)” from M11, M29 and M30, which the notice does not mention, and renumbers „Girație Pod Bega” (listed under `sameNameSwaps`).
- 4.30 → 4.31 (5 Nov), line E3: the Podul Polonă closure (notice 11062).

The pipeline reads each notice against the current feed (4.31), which already runs the 11060 and 11062 diversions, so on those notices it finds no row. The prepared Mocioni case (built on the 4.29 pattern, SPEC 5.3) is scored too, under `overall.independentGold.preparedCases`. The full diff is written to `results/gold_gtfs_diff.json`.

## Hero figures (D-012)

`run.py` copies the stored hero closure (`cl_20261108_16dec`) into its temporary state dir, applies the clerk decisions of the 11067 gold label (tick the unsure line 7 rows the label lists as suspended, untick the ring rows it lists as uncertain) and reads the impact. The result is the `hero` block: `stopsSuspended`, `departuresLost`, `residentsLosingStop` (model GHSL 2020, nu recensământ), `stopRoutePairsLost`, with provenance. `demoCaseUntouched` checks the stored demo case did not change.

## Output: `results/latest.json`

- `notices[]`: per notice, the rows found, the precision and recall (`strict` = only `affected` rows count as suspended; `lenient` = „neclar” (`unsure`) rows count too), the share sent to „neclar”, the number of `unread` sentences, whether the window matches, and the paste-to-alert time.
- `overall`: the same metrics summed over all notices (micro-average).
- `e3`: the figure above, with its method and provenance.
- A value that could not be measured is `null`, never 0. `errors[]` says why.

The README, the deck and `docs` copy numbers only from this file.
