"""Build Berlin June 2024 analysis tables in a DuckDB file.
segments: one row per (vehicle, status period) with start/end, prev/next status, first/last position, charge first/last/max/min.
"""
import os as _os
_REPO = _os.environ.get("MILES_REPO", _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../../.."))) + "/"  # repo root; raw data goes in data/ (see README)
import duckdb, json, sys
import shapely
from shapely.geometry import Polygon

DB = sys.argv[1]
PQ = _REPO + "data/miles/changes"
FILES = [f"{PQ}/2024-06-{d}.parquet" for d in ("03", "10", "17", "24")]
c = duckdb.connect(DB)
c.execute("SET threads=8; SET preserve_insertion_order=false")
c.execute(f"""
CREATE OR REPLACE TABLE r AS
SELECT time, vehicle_id, status, status_changed_from, latitude lat, longitude lon, charge, charging, discounted, damage_count
FROM read_parquet({FILES}) WHERE city = 'BER'""")
# segment id = running count of status-change rows per vehicle
c.execute("""
CREATE OR REPLACE TABLE r2 AS
SELECT *, sum(CASE WHEN status_changed_from IS NOT NULL THEN 1 ELSE 0 END) OVER (PARTITION BY vehicle_id ORDER BY time ROWS UNBOUNDED PRECEDING) seg
FROM r""")
c.execute("""
CREATE OR REPLACE TABLE seg AS
WITH s AS (
  SELECT vehicle_id, seg, min(time) t0, arg_min(status, time) status,
         arg_min(lat, time) FILTER (lat IS NOT NULL) lat0, arg_min(lon, time) FILTER (lon IS NOT NULL) lon0,
         arg_max(lat, time) FILTER (lat IS NOT NULL) lat1, arg_max(lon, time) FILTER (lon IS NOT NULL) lon1,
         count(lat) n_fix,
         arg_min(charge, time) FILTER (charge IS NOT NULL) ch0, arg_max(charge, time) FILTER (charge IS NOT NULL) ch1,
         max(charge) ch_max, min(charge) ch_min,
         bool_or(discounted) disc_any, bool_or(charging) charging_any,
         max(damage_count) dmg_max, min(damage_count) dmg_min
  FROM r2 GROUP BY ALL)
SELECT *,
  lead(t0) OVER w t1, lag(status) OVER w prev_status, lead(status) OVER w next_status,
  lag(status, 2) OVER w prev2_status
FROM s WINDOW w AS (PARTITION BY vehicle_id ORDER BY seg)""")
# forward-fill positions/charge/damage across segments
c.execute("""
CREATE OR REPLACE TABLE seg AS
SELECT *,
  coalesce(lat1, last_value(lat1 IGNORE NULLS) OVER w) plat, coalesce(lon1, last_value(lon1 IGNORE NULLS) OVER w) plon,
  last_value(lat1 IGNORE NULLS) OVER wp prev_lat, last_value(lon1 IGNORE NULLS) OVER wp prev_lon,
  last_value(ch1 IGNORE NULLS) OVER wp prev_ch, last_value(dmg_max IGNORE NULLS) OVER wp prev_dmg,
  epoch(t1 - t0)/3600.0 dur_h
FROM seg
WINDOW w AS (PARTITION BY vehicle_id ORDER BY seg ROWS UNBOUNDED PRECEDING),
       wp AS (PARTITION BY vehicle_id ORDER BY seg ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)""")

# zone flags for parked positions
areas = [a for a in json.load(open(_REPO + "miles-atlas/build/input/meta.json"))["areas"] if a["city"] == "BER"]
def poly(a):
    rings = a["rings"]
    return Polygon(rings[0], rings[1:]).buffer(0)
service = shapely.union_all([poly(a) for a in areas if a["kind"] == "service"])
nopark = shapely.union_all([poly(a) for a in areas if a["kind"] == "noparking"])
pts = c.execute("SELECT vehicle_id, seg, plon, plat FROM seg WHERE plat IS NOT NULL AND status='DEPLOYED_FOR_RENTAL'").fetchall()
import numpy as np
xy = np.array([(p[2], p[3]) for p in pts])
geoms = shapely.points(xy)
in_service = shapely.contains_xy(service, xy[:, 0], xy[:, 1])
in_nopark = shapely.contains_xy(nopark, xy[:, 0], xy[:, 1])
import pandas as pd
flags = pd.DataFrame({"vehicle_id": [p[0] for p in pts], "seg": [p[1] for p in pts], "in_service": in_service, "in_nopark": in_nopark})
c.execute("CREATE OR REPLACE TABLE zone AS SELECT * FROM flags")
print(c.execute("SELECT count(*), sum(in_service::INT), sum(in_nopark::INT) FROM zone").fetchall())
print(c.execute("SELECT count(*) segs, count(DISTINCT vehicle_id) cars FROM seg").fetchall())
