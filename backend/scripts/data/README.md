# Data fetch scripts

`fetch_all.sh` downloads the external sources into `$DATA_DIR` (and the
recordings' first files into `$LIVE_DIR`, default `$DATA_DIR/live`), prints
their versions and sha256, and writes `$DATA_DIR/provenance/sources.json`.

```sh
DATA_DIR=/path/to/data backend/scripts/data/fetch_all.sh      # from repo/
DATA_FREEZE=1 DATA_DIR=/path/to/data backend/scripts/data/fetch_all.sh   # no downloads
```

It is idempotent: a file already present is reused, so a rerun downloads
nothing unless Geofabrik has published a newer Romania extract (the city
sources below are asked again on every run; a file changes only when its
source did). With
`DATA_FREEZE=1` it never downloads; it only checks the local files, reruns the
crop and the validator smoke test and rewrites `sources.json`. If a download
fails and an older file exists, the old file is kept and its provenance note
says „memorat, sursa indisponibilă”.

Needs: `curl`, `unzip`, `uv`, `osmium-tool`, Java 21 (`openjdk-21-jre-headless`)
and Docker (only to copy the validator jar out of its image). On Ubuntu 24.04:

```sh
sudo apt-get install -y openjdk-21-jre-headless osmium-tool fonts-noto-core \
  libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0
```

(the last three are for WeasyPrint, which renders the stop poster).

## Sources

| Output in `$DATA_DIR` | Source | Version | Licence |
|---|---|---|---|
| `osm/timisoara.osm.pbf` | [Geofabrik](https://download.geofabrik.de/europe/romania.html) `romania-latest.osm.pbf`, cut with `osmium extract -b 21.10,45.68,21.35,45.83`. The dated upstream file stays in `osm/raw/` | the Geofabrik file name (`romania-YYMMDD`) and its replication timestamp | [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/), © OpenStreetMap contributors |
| `pop/ghsl_2020_100m.tif` | [GHSL](https://human-settlement.emergency.copernicus.eu/) GHS-POP, epoch 2020, release R2023A, 3 arcsec (~100 m), EPSG:4326, tile R5_C21 from the [JRC open data FTP](https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/GHS_POP_E2020_GLOBE_R2023A_4326_3ss/V1-0/), cropped to the same bbox (whole pixels, no resampling). The tile stays in `pop/raw/` | R2023A V1-0 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), © European Union 1995-2026. Cite: Schiavina M., Freire S., Carioli A., MacManus K. (2023), GHS-POP R2023A, European Commission JRC, doi:10.2905/2FF68A52-5B5B-4A22-8F40-C41DA8332CFE |
| `tools/gtfs-realtime-validator-webapp-1.0.0-SNAPSHOT.jar` | [MobilityData gtfs-realtime-validator](https://github.com/MobilityData/gtfs-realtime-validator). The project publishes no GitHub release; the jar is copied from its official image `ghcr.io/mobilitydata/gtfs-realtime-validator`, pinned by digest in `fetch_all.sh` | 1.0.0-SNAPSHOT (image built 2024-11-26) | [Apache-2.0](https://github.com/MobilityData/gtfs-realtime-validator/blob/master/LICENSE) |

The population grid is a model: every figure built on it carries the label
„model GHSL 2020, 100 m (nu recensământ)”.

## City sources and the live recording

`fetch_all.sh` first runs `fetch_city.py` (alone: `make data-city`, which needs
no osmium or Java). It writes the files the backend reads:

| Source | Output |
|---|---|
| SMTT GTFS `https://smtt.ro/transit/gtfs/maps/smtt-timisoara-ro.zip` (conditional GET on the ETag; `feed_info.txt` checked) | `$LIVE_DIR/gtfs/smtt_<etag>.zip`, a new file only when the feed changed; the backend serves the newest |
| GTFS 4.29 and 4.30, Mobility Database mirror (`mdb-2868`), pinned by sha256 | `$DATA_DIR/gtfs-history/`, downloaded once |
| `cont.primariatm.ro/api/mobile/transit/network`, `/api/zones`, `/api/mobile/parking`, `servicii.primariatm.ro/api/nomenclator/strazi` | `$DATA_DIR/city-api-2026-11-13/` (`transit-network.json`, `zones.geojson`, `parking.json`, `nomenclator-strazi.json`), as served |
| stpt.ro WordPress API, newest 20 posts | `$LIVE_DIR/stpt-posts/<id>_<modified>.json`; an edited post gets a new file |
| `sesizari.primariatm.ro/api/sesizari`, last 2 days, without the report text | `$LIVE_DIR/sesizari/YYYYMMDD-HHMM.json` (UTC) |

GET only, with a User-Agent that names the team. Every download goes to a
staging dir and is checked (JSON shape and counts, zip CRC, the GTFS files);
only then it replaces the real file, by an atomic rename. A failed or bad
source keeps the last good file, and its record says „memorat, sursa
indisponibilă”; the script exits 1 only when a source has no file at all.
`DATA_FREEZE=1` downloads nothing. Each source gets a record in
`provenance/parts/` (ids `smtt-gtfs`, `gtfs-history:<file>`, `city-network`,
`city-zones`, `city-parking`, `city-streets`, `stpt-posts`, `city-sesizari`).
`sources.json` also lists every GTFS zip and city-API file on disk under
`local` (size, sha256, mtime, GTFS `feed_version`).

`record_vehicles.py` records the CityApp live vehicles feed
(`cont.primariatm.ro/api/mobile/transit/vehicles`, undocumented, no
guarantee) every 15 s into `$LIVE_DIR/vehicles/YYYYMMDD-HH.jsonl.gz` (UTC hour,
one JSON line per poll, each line its own gzip member). It never polls faster
than every 10 s and does not start when another program is writing into the
same directory.

```sh
make record     # tmux rv-record: window `vehicles` (every 15 s), window `city`
                # (fetch_city.py --every 3600 --only gtfs,stpt,sesizari)
tmux kill-session -t rv-record   # stop
```

## What the script checks

- OSM: the md5 Geofabrik publishes next to the file; prints the bbox and the
  node, way and relation counts of the extract.
- GHSL: the zip CRC; that the tile is EPSG:4326 and covers 21.2E 45.75N; prints
  the crop's bounds, size and resolution, the population summed over the bbox
  and inside the 40 city zones (`city-api-*/zones.geojson`, pixel centre inside
  a zone).
- Validator: runs the batch CLI against the newest GTFS zip on a one-alert
  GTFS-RT feed whose stop id is not in the GTFS, and checks that it reports rule
  E011 („stop_id does not exist in GTFS data”). That proves it loaded the GTFS
  and validated the feed.

## Using the validator

```sh
java -cp "$DATA_DIR/tools/gtfs-realtime-validator-webapp-1.0.0-SNAPSHOT.jar" \
  edu.usf.cutr.gtfsrtvalidator.lib.Main -gtfs GTFS.zip -gtfsRealtimePath DIR_WITH_PB_FILES
```

It writes `<file>.results.json` next to each feed file in `DIR_WITH_PB_FILES`.

## `provenance/sources.json`

```
{ generatedAt, generatedBy, dataFreeze,
  fetched: [{ id, source, url, version, fetchedAt, note, license, file, bytes, sha256,
              upstream?: { url, file, bytes, sha256 } }],
  local:   [{ id, source, url, version, fetchedAt, note, license, file, bytes, sha256 }] }
```

`source`, `url`, `version`, `fetchedAt` and `note` are the fields of the API's
`Provenance` type, so the backend can copy a record into a response as it is.
`fetchedAt` is the time the file was downloaded (its mtime), in UTC.

## Files

- `fetch_all.sh`: the entry point.
- `fetch_city.py`: the city sources (GTFS, city API, STPT notices, sesizări).
- `record_vehicles.py`: the live vehicle recorder (`make record`).
- `ghsl_crop.py`: crops the GHSL tile and prints the sanity numbers.
- `provenance.py`: writes one record per fetched source and merges them into `sources.json`.
- `gtfsrt_smoke_feed.py`: writes the header-only GTFS-RT feed for the validator smoke test.

The Python helpers run in throwaway `uv run --with` environments with pinned
versions (`fetch_city.py` and `record_vehicles.py` need only the standard
library), so they do not depend on the backend's virtual environment.
