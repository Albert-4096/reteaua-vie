# Held-out STPT notices (V1)

Five real STPT notices that no parser test and no eval label had used. The question: does the parser read
a notice it has never seen?

**Source.** Our recording of the stpt.ro WordPress posts (`$LIVE_DIR/stpt-posts/<id>_<time>.json`, newest
copy per post). Nothing was fetched for this check.

**Selection.** The 5 most recent recorded posts that change a line and appear neither in
`backend/tests/test_m1_notices*.py` nor in `eval/labels/`:

- 10899 (9 Oct)
- 10876 (30 Sep)
- 10874 (29 Sep)
- 10862 (17 Sep)
- 10853 (11 Sep)

What was left out:

- 11070, 11019, 11017, 10960 and 10858 change no line (fleet news, boats, results, an environmental notice, a campaign).
- 10872 (28 Sep) would come before 10862 by date. It is left out because its parser output was inspected while R29 was built, so it is not held out.

**Method.**

- First pass on commit `da7f638`, before any parser change.
- Title + text pasted as a person copies them. `POST /api/closures/parse`, then `POST /api/closures/{id}/analyze`.
- Run on a private server (127.0.0.1:3009) with a copied DATA_DIR state, never on the public demo.
- Each field is scored against the text:
  - `ok`: right, or nothing to read and nothing invented.
  - `greșit`: wrong, or something named in the text is dropped without a word.
  - `neclar`: part of it is read; the rest is sent to the person as an unread sentence.
- Raw notes per notice below. The first-pass score is the reported number.

## Scores

| Field | First pass (held-out) | After fix, not held-out |
|---|---|---|
| Lines | 2/5 ok, 3 greșit | 3/5 ok, 2 neclar, 0 greșit |
| Direction | 5/5 ok (3 of them: no direction in the text, none invented) | 5/5 ok |
| Window | 2/5 ok, 3 greșit | 5/5 ok |
| Stops | 3/5 ok, 2 neclar, 0 greșit | 3/5 ok, 2 neclar, 0 greșit |

## Per notice (first pass)

### 10899: timetable changes, lines 32, 46, S13, S14b (no closure)

| Field | Result | What the text says / what we gave |
|---|---|---|
| Lines | greșit | „liniile 32 și 46 … S13 și S14b”: we give 32 and 46; S13 and S14b (school lines, not in the GTFS) are dropped with no unread sentence |
| Direction | ok | no direction in the text; none given |
| Window | ok | „începând cu 12 octombrie 2026”: from 12 Oct, open end |
| Stops | ok | no stop is suspended; 0 rows |

### 10876: extra trips on S7 and S14 B (no closure)

| Field | Result | What the text says / what we gave |
|---|---|---|
| Lines | greșit | „liniile S7 și S14 B”: not in the GTFS; we give no line and no unread sentence names them |
| Direction | ok | none in the text, none given |
| Window | greșit | title „de la 1 octombrie”, text „începând cu 1 octombrie 2026”: from 1 Oct, open end; we give 1 Oct only (00:00 – 2 Oct 00:00), read from the title |
| Stops | ok | 0 rows |

### 10874: timetable changes on 33, 40, E8, M24, M32 (no closure)

| Field | Result | What the text says / what we gave |
|---|---|---|
| Lines | ok | 33, 40, E8, M24, M32: all five |
| Direction | ok | none in the text, none given |
| Window | greșit | title „de la 1 octombrie”, text „începând cu 1 octombrie 2026”: we give 1 Oct only, read from the title |
| Stops | ok | 0 rows |

### 10862: Ziua Mobilității (C.D. Loga – 20 Decembrie 1989 – Podul Mihai Viteazu closed)

| Field | Result | What the text says / what we gave |
|---|---|---|
| Lines | greșit | „Liniile 32, 33 și 33B”, 16, Expres 3: we give 32, 33, 16, E3; 33B (not in the GTFS) is dropped without a word; line 15 („pe traseul liniei 15”) is correctly not taken |
| Direction | ok | 16: „Pe sensul tur” / „Pe sensul retur”, one list each, opposite directions; E3: only „Pe sensul retur” has stops, we give only that direction |
| Window | greșit | „19 septembrie, ora 05:00 – 20 septembrie, ora 05:00”: we give 19 Sep 05:00 – 31 Dec, because the vaporetto sentence („începând cu ora 17:11”, open end) is taken as a part of the window |
| Stops | neclar | 16 and E3: 11 rows, all named in the text. Not in the analysis but listed as unread: „Stația Catedrala Mitropolitană va fi suspendată temporar” (32, 33), „vor întoarce la Piața Regina Maria”, and the two 16 lists with names the GTFS spells otherwise („Bulevardul I.C. Brătianu”, „Piața Iancu Huniade”) |

### 10853: Reborn Run (Vasile Pârvan closed between Mihai Viteazu and Pasaj Michelangelo)

| Field | Result | What the text says / what we gave |
|---|---|---|
| Lines | ok | „liniile 16, Expres 8, Expres 7 și Expres 3”: all four |
| Direction | ok | every „Pe sensul spre …” / „Pe sensul de întoarcere” list lands on the direction with that headsign |
| Window | ok | „duminică, 13 septembrie 2026, în intervalul orar 05:00–20:00”: 13 Sep 05:00–20:00 |
| Stops | neclar | 21 rows, all named in the text; 3 names not found and their sentences listed as unread: „bulevardul I.C. Brătianu”, „Piața Iancu Huniade”, „Complexul Studențesc (strada Cluj)” |

## After the fix (not held-out)

What changed in the parser, then the same five notices again. These scores are not held-out: the
notices were read to make the fixes, and they are now parser tests (`backend/tests/test_m1_notices_r29.py`).

- **Window.** „de la 1 octombrie” opens a window with no end, like „începând cu” (10876, 10874). A sentence
  that itself has no end („începând cu ora 17:11”) is no longer taken as part of a whole-day window
  (10862: now 19 Sep 05:00 – 20 Sep 05:00).
- **Lines.** „32, 33 și 33B” no longer reads „și 33B” as one token: 33B is in the GTFS (`R_AB_33B`) and is now
  found. The first-pass note for 10862 was wrong on the cause: 33B was lost to that token, not because it is
  missing from the GTFS. The first-pass score stays greșit. A line that really is not in the GTFS (S7, S13,
  S14 B) now puts its sentences in `unread` instead of being dropped; that is `neclar` for 10899 and 10876.
- **Stops.** The singular „Stația Catedrala Mitropolitană va fi suspendată temporar” is read (10862: +6 rows,
  stop 326 on 32, 33 and 33B, both directions). Still `neclar`: „vor întoarce la …” and the names the GTFS
  spells otherwise.

| Notice | Lines | Direction | Window | Stops |
|---|---|---|---|---|
| 10899 | neclar (32, 46; S13 and S14b sentences listed) | ok | ok (12 Oct, open end) | ok (0) |
| 10876 | neclar (S7, S14 B sentences listed) | ok | ok (1 Oct, open end) | ok (0) |
| 10874 | ok | ok | ok (1 Oct, open end) | ok (0) |
| 10862 | ok (32, 33, 33B, 16, E3) | ok | ok (19 Sep 05:00 – 20 Sep 05:00) | neclar (17 rows) |
| 10853 | ok | ok | ok | neclar (21 rows) |
