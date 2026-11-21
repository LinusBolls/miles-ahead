# geo/

Geospatial artifacts the ops backend loads at startup.

Committed:

- `paid_zones.geojson` — Berlin paid / restricted parking-zone polygons derived from **OpenStreetMap** (public data).

**Not committed** (MILES-derived or large; excluded by `.gitignore`, rebuilt from the private scraper DB via
`../build_replay.py`, `../geo_compact.py` and `../preprocess.py`):

- `berlin_geo.pkl.gz` — street / parking classification trees.
- `replay_berlin_2024-06.{parquet,npz}`, `replay_meta.json` — the June 2024 replay ride-end stream (licence plates
  are masked to `B-MI ••NN` in `replay_meta.json`).
- `cells_berlin.json` — aggregate per-cell ride-end history used as a feature.
- `demand_berlin.npz` — aggregate demand grid.
