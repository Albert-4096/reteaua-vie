"""L0, the observed timetable: our vehicle recording turned into GTFS-like measured stop times.

From the recording ($LIVE_DIR/vehicles/YYYYMMDD-HH.jsonl.gz, one UTC hour per file) and the
SMTT GTFS in force on each service date, `app.observed.build` writes, per recorded hour, under
$DATA_DIR/cache/observed/v<N>/:

- reports/<hour>.parquet   the hour's vehicle reports, de-duplicated on (vehicle, updatedAt)
- events/<hour>.parquet    one row per (trip, stop, service date) whose arrival (else
                           departure) falls in that hour: observed arrival and departure,
                           dwell, our stop delay, the feed's delaySec, `interpolated`
- segments/<hour>.parquet  one row per consecutive stop pair of a trip whose departure from
                           the first stop falls in that hour: run time, hour (Bucharest), day type
- manifest.json            per built hour: counts, feed version, built time

An hour that is built is never rebuilt (bump VERSION in build.py to rebuild everything).
Consumers read `app.observed.store`, never the raw recording, so every screen counts alike.
Raw and derived recording data stay in $DATA_DIR, never in the repo.
"""
