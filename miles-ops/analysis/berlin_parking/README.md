> **In this repo:** the scripts only. The GeoJSON files below are open data and not committed (one is 170 MB);
> download them from the WFS services listed below into `data/berlin_parking/` at the repo root. `events_base.py`
> also reads `miles-atlas/build/input/meta.json` (MILES business-area polygons from the dataset's metadata), which is
> not committed yet (pending). Run order: `events_base.py <db.duckdb>`, then `parking_enrich.py <db.duckdb>`, which
> writes `data/berlin_parking/parks_berlin_2024-06.parquet` for `../parking_outcomes.py`.

# Berlin parking datasets (downloaded 2026-11-21)

All files are from Berlin's official geodata service (gdi.berlin.de, WFS) as GeoJSON in EPSG:4326. The licence is Datenlizenz Deutschland Zero 2.0 (no attribution required).

| file | what | features | key fields |
|---|---|---|---|
| `street_parking_inner.geojson` | every street-parking section inside the S-Bahn ring (scan-car survey, 2023) | 45,917 | `beschraenkung` (Haltverbot / Eingeschränktes Haltverbot), `grund_fuer_beschraenkung` (Ladezone, Bussonderfahrstreifen, Taxi, …), `geltungszeit_der_beschraenkung`, `parkort` (Fahrbahn / Parkbucht / Gehwegparken), `parkgebuehr`, `bewirtschaftungszeit`, `hoechstparkdauer`, `carsharing`, `ladesaeule`, `nur_schwerbehinderte` |
| `street_parking_outer.geojson` | street-parking sections outside the ring (derived from other data, no scan car, so less precise) | 214,173 | same schema |
| `paid_parking_zones.geojson` | paid-parking zones (Parkraumbewirtschaftung), as of 2025-04 | 104 | `parkzone`, `bezirk`, `zeiten`, `gebuehr` (EUR/h), `parkstaende` |
| `micromobility_no_parking.geojson` | no-parking zones for rental scooters and bikes (not cars, but shows sensitive areas) | – | – |

How to read it:
- Legal parking = inside a street-parking polygon whose `beschraenkung` is empty.
- Restricted = inside a polygon with `beschraenkung` set. Check `geltungszeit_der_beschraenkung`, since many restrictions are time-limited, e.g. loading zones Mon–Fri 7–17.
- Anything far from every polygon (sidewalk, crossing, square) has no legal street parking.

Source services:
- `https://gdi.berlin.de/services/wfs/parkplaetze` (layers `parkplaetze:parkplaetze`, `parkplaetze:parkplaetze_aussen`)
- `https://gdi.berlin.de/services/wfs/parkraumbewirtschaftung` (layer `parkraumbewirtschaftung:parkzonen`)
- `https://gdi.berlin.de/services/wfs/parkverbot_mikromob` (layer `parkverbot_mikromob:parkverbot_mikromobilitaet`)

Analysis script: `parking_check.py` (needs the Berlin June segment table, built by `events_base.py` in the session scratchpad). It tests MILES ride-end positions from June 2024 against these layers.

## Integrated with the MILES time series: `parks_berlin_2024-06.parquet`
One row per parking period after a customer ride: 306,538 rows, Berlin, 3–30 June 2024.
- `vehicle_id`, `parked_from_utc`, `parked_hours`, `latitude`, `longitude`
- `area_type` (enum):
  - `legal` (within 20 m of a legal street-parking section)
  - `no_legal_parking_nearby` (inside the S-Bahn ring, >20 m from any legal section)
  - `no_legal_parking_nearby_outer` (same outside the ring, where the data is less precise)
  - `no_stopping`, `loading_zone`, `bus_lane`, `taxi_stand` (inside a restricted section)
- `dist_to_legal_parking_m`: continuous. Prefer it over the enum for modelling, since GPS error is about 10 m.
- `restriction_type`, `restriction_reason`, `restriction_hours`: when the restriction applies. Empty means always; otherwise check it against `parked_from_utc` and `parked_hours`.
- `paid_zone`, `paid_zone_fee_eur_h`, `paid_zone_hours`
- `inside_sbahn_ring`

Rebuild or extend to other weeks: `events_base.py <db>` (segments from `changes/*.parquet`), then `parking_enrich.py <db>`.
