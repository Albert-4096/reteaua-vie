#!/usr/bin/env bash
# Fetch the external data sources that no other tool records, into $DATA_DIR:
#   - OSM: Geofabrik romania-latest.osm.pbf, cut to the Timișoara bbox (osmium)
#   - Population: GHSL GHS-POP epoch 2020, R2023A, 3 arcsec, EPSG:4326, cropped
#   - Tool: MobilityData gtfs-realtime-validator (batch CLI jar)
#   - City sources (fetch_city.py): SMTT GTFS, GTFS 4.29/4.30, the city API
#     copies, STPT notices, sesizări. Live vehicles: record_vehicles.py (`make record`).
#
# Idempotent: a file already present is reused. DATA_FREEZE=1 never downloads.
# If a download fails and an older file exists, that file is kept and its
# provenance note says „memorat, sursa indisponibilă”.
# Prints versions and sha256, writes $DATA_DIR/provenance/sources.json.
#
# Needs: curl, unzip, osmium-tool, java 21, docker (validator), uv.
# Usage: DATA_DIR=/path/to/data backend/scripts/data/fetch_all.sh
set -euo pipefail

: "${DATA_DIR:?set DATA_DIR to the data directory}"
DATA_DIR="$(cd "$DATA_DIR" && pwd)"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FREEZE="${DATA_FREEZE:-0}"

BBOX="21.10,45.68,21.35,45.83"
GEOFABRIK="https://download.geofabrik.de/europe"
GHSL_BASE="https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/GHS_POP_E2020_GLOBE_R2023A_4326_3ss/V1-0"
# Tile row 5, column 21 of the 4326 grid: covers 21.2E 45.75N (checked by ghsl_crop.py).
GHSL_TILE="GHS_POP_E2020_GLOBE_R2023A_4326_3ss_V1_0_R5_C21"
# The validator has no GitHub release; its official build is the MobilityData
# GHCR image. Pinned by digest so a rerun gets the same jar.
VALIDATOR_IMAGE="ghcr.io/mobilitydata/gtfs-realtime-validator@sha256:ef437eb291259ba16a3a4a0e9a83b18f597a365e3a0fdc9a8a5b73d4a541333d"
VALIDATOR_JAR_NAME="gtfs-realtime-validator-webapp-1.0.0-SNAPSHOT.jar"
VALIDATOR_MAIN="edu.usf.cutr.gtfsrtvalidator.lib.Main"

PY=(uv run --no-project --quiet --python 3.12 python -I)
PY_GEO=(uv run --no-project --quiet --python 3.12 --with rasterio==1.5.2 --with numpy==2.5.4 python -I)
PY_RT=(uv run --no-project --quiet --python 3.12 --with gtfs-realtime-bindings==3.0.0 python -I)

log() { printf '\n== %s\n' "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null || die "missing $1 ($2)"; }

# download URL DEST: atomic (DEST appears only when complete); mtime = fetch time.
download() {
  mkdir -p "$(dirname "$2")"
  echo "  GET $1"
  curl -fL --retry 3 --retry-delay 5 -sS -o "$2.part" "$1" && mv "$2.part" "$2"
}

# newest GLOB...: the last matching path by name, or nothing (never fails).
newest() { { ls -1 "$@" 2>/dev/null || true; } | sort | tail -n 1; }

fetch_osm() {
  log "OSM: Geofabrik romania, bbox $BBOX (ODbL 1.0)"
  local dir="$DATA_DIR/osm" name="" raw note=""
  mkdir -p "$dir/raw"
  if [[ $FREEZE != 1 ]]; then
    # romania-latest redirects to the dated file (romania-YYMMDD.osm.pbf).
    name="$(curl -sSI -m 30 "$GEOFABRIK/romania-latest.osm.pbf" | tr -d '\r' \
      | awk 'tolower($1)=="location:"{print $2}' | xargs -r basename)" || name=""
  fi
  if [[ -n $name && ! -s $dir/raw/$name ]]; then
    if download "$GEOFABRIK/$name" "$dir/raw/$name"; then
      local expected actual
      expected="$(curl -fsS -m 30 "$GEOFABRIK/$name.md5" | cut -d' ' -f1)"
      actual="$(md5sum "$dir/raw/$name" | cut -d' ' -f1)"
      [[ $expected == "$actual" ]] || { rm -f "$dir/raw/$name"; die "md5 mismatch for $name"; }
      echo "  md5 ok $actual"
    else
      rm -f "$dir/raw/$name.part"; name=""
    fi
  elif [[ -n $name ]]; then
    echo "  have $name (newest on Geofabrik), not downloading"
  fi
  if [[ -z $name ]]; then
    raw="$(newest "$dir"/raw/romania-*.osm.pbf)"
    [[ -n $raw ]] || die "no OSM file and Geofabrik unreachable"
    name="$(basename "$raw")"
    [[ $FREEZE == 1 ]] || note="memorat, sursa indisponibilă"
    echo "  using local $name ${note:+($note)}"
  fi
  raw="$dir/raw/$name"

  local out="$dir/timisoara.osm.pbf" ts
  if [[ ! -s $out || $raw -nt $out ]]; then
    osmium extract -b "$BBOX" --overwrite -o "$out" "$raw"
  else
    echo "  extract up to date"
  fi
  ts="$(osmium fileinfo -g header.option.osmosis_replication_timestamp "$raw")"
  echo "  Geofabrik file $name, replication timestamp $ts"
  osmium fileinfo -e "$out" | grep -E 'Bounding box|Number of (nodes|ways|relations)' | sed 's/^ */  /'
  "${PY[@]}" "$HERE/provenance.py" part "$DATA_DIR" osm osm/timisoara.osm.pbf \
    --source "OpenStreetMap via Geofabrik" \
    --url "$GEOFABRIK/romania-latest.osm.pbf" \
    --version "$name, OSM data until $ts" \
    --license "ODbL 1.0, © OpenStreetMap contributors" \
    --note "osmium extract -b $BBOX${note:+; $note}" \
    --upstream-file "osm/raw/$name" --upstream-url "$GEOFABRIK/$name"
}

fetch_ghsl() {
  log "Population: GHSL GHS-POP 2020, R2023A, 3 arcsec, EPSG:4326 (CC BY 4.0)"
  local dir="$DATA_DIR/pop" zip tif note=""
  zip="$dir/raw/$GHSL_TILE.zip"
  tif="$dir/raw/$GHSL_TILE.tif"
  mkdir -p "$dir/raw"
  if [[ ! -s $zip ]]; then
    [[ $FREEZE != 1 ]] || die "DATA_FREEZE=1 and $zip is missing"
    download "$GHSL_BASE/tiles/$GHSL_TILE.zip" "$zip" || die "GHSL download failed and no local copy"
  else
    echo "  have $GHSL_TILE.zip, not downloading (a GHSL release never changes)"
  fi
  unzip -tq "$zip" >/dev/null || die "$zip is corrupt"
  if [[ ! -s $tif || $zip -nt $tif ]]; then
    unzip -o -j -q -d "$dir/raw" "$zip" "$GHSL_TILE.tif"
    # The zip stores mode 0700; the team group must be able to read the tile.
    touch "$tif" && chmod 0664 "$tif"
  fi
  local zones
  zones="$(newest "$DATA_DIR"/city-api-*/zones.geojson)"
  "${PY_GEO[@]}" "$HERE/ghsl_crop.py" "$tif" "$dir/ghsl_2020_100m.tif" "$BBOX" ${zones:+"$zones"}
  "${PY[@]}" "$HERE/provenance.py" part "$DATA_DIR" ghsl pop/ghsl_2020_100m.tif \
    --source "GHSL population grid (JRC)" \
    --url "$GHSL_BASE/tiles/$GHSL_TILE.zip" \
    --version "GHS-POP R2023A V1-0, epoch 2020, 3 arcsec, EPSG:4326, tile R5_C21" \
    --license "CC BY 4.0, © European Union 1995-2026; Schiavina et al. (2023), doi:10.2905/2FF68A52-5B5B-4A22-8F40-C41DA8332CFE" \
    --note "model GHSL 2020, 100 m (nu recensământ); cropped to $BBOX${note:+; $note}" \
    --upstream-file "pop/raw/$GHSL_TILE.zip" --upstream-url "$GHSL_BASE/tiles/$GHSL_TILE.zip"
}

fetch_validator() {
  log "Tool: MobilityData gtfs-realtime-validator (Apache-2.0)"
  local dir="$DATA_DIR/tools" jar pinned
  jar="$dir/$VALIDATOR_JAR_NAME"
  pinned="$dir/gtfs-realtime-validator.image"
  mkdir -p "$dir"
  if [[ ! -s $jar || "$(cat "$pinned" 2>/dev/null)" != "$VALIDATOR_IMAGE" ]]; then
    [[ $FREEZE != 1 ]] || die "DATA_FREEZE=1 and $jar is missing"
    need docker "to copy the validator jar out of its image"
    echo "  docker pull $VALIDATOR_IMAGE"
    docker pull -q "$VALIDATOR_IMAGE" >/dev/null
    local cid
    cid="$(docker create "$VALIDATOR_IMAGE")"
    # touch: docker cp keeps the image's mtime; fetchedAt must be the copy time.
    docker cp -q "$cid:/app/$VALIDATOR_JAR_NAME" "$jar.part" && touch "$jar.part" && mv "$jar.part" "$jar"
    docker rm "$cid" >/dev/null
    echo "$VALIDATOR_IMAGE" > "$pinned"
  else
    echo "  have $VALIDATOR_JAR_NAME from the pinned image"
  fi

  # Smoke test: an alert on an unknown stop id, against the newest GTFS we hold.
  # A working validator loads the GTFS and reports E011.
  local gtfs tmp
  gtfs="$(newest "$DATA_DIR"/live/gtfs/*.zip)"
  [[ -n $gtfs ]] || gtfs="$(newest "$DATA_DIR"/smtt-*.zip)"
  [[ -n $gtfs ]] || die "no GTFS zip in $DATA_DIR for the validator smoke test"
  tmp="$(mktemp -d)"
  "${PY_RT[@]}" "$HERE/gtfsrt_smoke_feed.py" "$tmp/smoke.pb"
  echo "  smoke test: -gtfs ${gtfs#"$DATA_DIR"/} -gtfsRealtimePath <tmp>/smoke.pb"
  java -cp "$jar" "$VALIDATOR_MAIN" -gtfs "$gtfs" -gtfsRealtimePath "$tmp" > "$tmp/validator.log" 2>&1 \
    || { tail -n 20 "$tmp/validator.log"; die "validator smoke test failed"; }
  local results
  results="$(ls "$tmp"/*results.json 2>/dev/null | head -n 1)"
  [[ -n $results ]] || { tail -n 20 "$tmp/validator.log"; die "validator wrote no results file"; }
  grep -q '"errorId" : "E011"' "$results" || { cat "$results"; die "validator did not report E011"; }
  echo "  validator ran: $(basename "$results") reports $(grep -o '"errorId" : "[EW][0-9]*"' "$results" \
    | cut -d'"' -f4 | sort -u | paste -sd, -) as expected (unknown stop id)"
  rm -rf "$tmp"

  "${PY[@]}" "$HERE/provenance.py" part "$DATA_DIR" gtfs-realtime-validator "tools/$VALIDATOR_JAR_NAME" \
    --source "MobilityData gtfs-realtime-validator" \
    --url "https://github.com/MobilityData/gtfs-realtime-validator" \
    --version "1.0.0-SNAPSHOT from ${VALIDATOR_IMAGE}" \
    --license "Apache-2.0" \
    --note "batch CLI: java -cp $VALIDATOR_JAR_NAME $VALIDATOR_MAIN -gtfs GTFS.zip -gtfsRealtimePath DIR"
}

fetch_city() {
  log "City sources: SMTT GTFS, city API, STPT notices, sesizări (fetch_city.py)"
  DATA_DIR="$DATA_DIR" "${PY[@]}" "$HERE/fetch_city.py"
}

main() {
  need curl ""; need unzip ""; need uv "Python runner"
  need osmium "sudo apt-get install osmium-tool"
  need java "sudo apt-get install openjdk-21-jre-headless"
  log "Tools"
  echo "  $(osmium --version | head -n 1)"
  echo "  $(java -version 2>&1 | head -n 1)"
  echo "  $(uv --version)"
  echo "  DATA_DIR=$DATA_DIR DATA_FREEZE=$FREEZE"

  fetch_city
  fetch_osm
  fetch_ghsl
  fetch_validator

  log "Provenance"
  "${PY[@]}" "$HERE/provenance.py" merge "$DATA_DIR"
  log "Fetched files (sha256)"
  (cd "$DATA_DIR" && sha256sum osm/timisoara.osm.pbf pop/ghsl_2020_100m.tif "tools/$VALIDATOR_JAR_NAME" \
    && ls -l osm/timisoara.osm.pbf pop/ghsl_2020_100m.tif "tools/$VALIDATOR_JAR_NAME" provenance/sources.json)
}

main "$@"
