# DATEX II v3.5 XML schemas (test fixture, not in git)

`tests/test_m7_datex.py` validates `GET /api/feed/datex.xml` against the official DATEX II
v3.5 XML schemas published by the DATEX II organisation on <https://docs.datex2.eu/downloads/modelv35/>.

**Licence:** the download page states "Copyright © 2025 DATEX II" and gives no licence for
redistribution, so the schemas are **not committed** here. The tests look for them, in order, in:

1. `$DATEX_XSD_DIR`
2. `$DATA_DIR/datex/xsd-3.5/`
3. `backend/fixtures/datex/xsd-3.5/` (a local download next to this note; do not commit it)

and skip the XSD check with a message when none exists.

## Fetch them once

```bash
mkdir -p "$DATA_DIR/datex/xsd-3.5" && cd "$DATA_DIR/datex/xsd-3.5"
for f in D2Payload Common CommonExtension LocationReferencing LocationExtension Situation \
         ReroutingManagementEnhanced TrafficManagementPlan UrbanExtensions RoadTrafficData \
         EnergyInfrastructure Parking Vms Facilities FaultAndStatus; do
  curl -sSfO "https://docs.datex2.eu/_static/data/v3.5/DATEXII_3_$f.xsd"
done
sha256sum -c <path to the repo>/backend/fixtures/datex/SHA256SUMS
```

`DATEXII_3_D2Payload.xsd` is the root schema; it imports the other 14 files.
`SHA256SUMS` holds the hashes of the files we downloaded and tested against on 13 Nov 2026.
