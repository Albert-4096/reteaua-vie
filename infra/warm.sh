#!/usr/bin/env bash
# Warm every endpoint the demo steps read, once, after the API starts.
# The first call after a start builds in-memory indexes (the overview took 12 s cold, 0.3 s warm).
# Usage: infra/warm.sh [base_url]   (default http://127.0.0.1:3000)
set -u
BASE="${1:-http://127.0.0.1:3000}"
HERO=cl_20261108_16dec
E3=cl_20261107_e3
MOC=cl_20261102_mocioni

paths=(
  /api/health /api/network /api/zones /api/cases /api/closures /api/overview
  /api/layers/parking /api/live/vehicles /api/live/missing "/api/live/missing?case=case_l23" /api/live/deviations
  /api/feed/alerts.json /api/feed/alerts.ngsi.json /api/feed/datex.xml
  /api/compliance /api/history /api/indicators /api/exports
  /api/observed/summary /api/lines/status /api/data-quality /api/registry /api/feed-diff
  /api/reliability/lines /api/reliability/vehicles /api/standing /api/streets/critical "/api/layers/streets"
  /api/accessibility/lines /api/accessibility/stops/6 /api/layers/accessibility
  /api/coverage/zones /api/layers/coverage /api/corridors
  /api/eta/backtest /api/feed/tripupdates.json /api/feed/tripupdates.pb
  /api/feed/waze-cifs.json /api/feed/avoid-streets.geojson /api/feed/notices.json
  /api/checkins /api/layers/road_issues /api/road-issues /api/reports/zones
)
for c in "$HERO" "$E3" "$MOC"; do
  paths+=(
    "/api/closures/$c" "/api/closures/$c/analysis" "/api/closures/$c/impact"
    "/api/closures/$c/notice" "/api/closures/$c/validation"
    "/api/closures/$c/bike" "/api/closures/$c/parking" "/api/closures/$c/detour-load"
    "/api/closures/$c/conflicts" "/api/closures/$c/reports" "/api/closures/$c/windows"
    "/api/closures/$c/access?dest=hospital&minutes=30" "/api/scenarios?closureId=$c"
    "/api/closures/$c/detour-cost" "/api/closures/$c/windows/measured" "/api/closures/$c/cut-through"
    "/api/closures/$c/balance" "/api/closures/$c/landmarks" "/api/closures/$c/paid-parking"
    "/api/closures/$c/km" "/api/closures/$c/journal"
  )
done
paths+=("/api/closures/$MOC/live")

fail=0
for p in "${paths[@]}"; do
  out=$(curl -s -m 120 -o /dev/null -w '%{http_code} %{time_total}' "$BASE$p") || out="000 -"
  printf '%s %ss %s\n' "${out% *}" "${out#* }" "$p"
  # 202 = a job started (it finishes in the background); 404 on /validation or /journal = not published / no journal yet
  case "${out% *}" in 200|202) ;; 404) [[ "$p" == */validation || "$p" == */journal ]] || fail=1 ;; *) fail=1 ;; esac
done
exit $fail
