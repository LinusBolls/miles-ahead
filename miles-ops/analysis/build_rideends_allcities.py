"""Ride-end dataset for all MILES cities, June 2024 (dense period), city-agnostic features.
One row per customer ride end (status -> DEPLOYED_FOR_RENTAL from USER_IN_RIDE/PAUSED_BY_USER), label idle > 12 h.
Output: miles-ops/analysis/rideends_allcities_2024-06.parquet
"""
import os as _os
_REPO = _os.environ.get("MILES_REPO", _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../.."))) + "/"  # repo root; raw data goes in data/ (see README)
import duckdb
D = _REPO + "data/miles/"
OUT = _REPO + "miles-ops/analysis/rideends_allcities_2024-06.parquet"
FILES = [D + f"changes/2024-{m}.parquet" for m in ["05-27", "06-03", "06-10", "06-17", "06-24", "07-01"]]
c = duckdb.connect()
c.execute("SET memory_limit='10GB'; SET threads=8")
c.execute(f"""
CREATE TABLE ff AS
SELECT vehicle_id, time, city,
  last_value(status IGNORE NULLS) OVER w status,
  last_value(latitude IGNORE NULLS) OVER w lat, last_value(longitude IGNORE NULLS) OVER w lon,
  last_value(charge IGNORE NULLS) OVER w charge, last_value(discounted IGNORE NULLS) OVER w discounted,
  last_value(damage_count IGNORE NULLS) OVER w damage_count
FROM read_parquet({FILES})
WHERE time >= '2024-05-27' AND time < '2024-07-08'
WINDOW w AS (PARTITION BY vehicle_id ORDER BY time ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)""")
c.execute("""
CREATE TABLE seg AS
WITH ch AS (SELECT *, lag(status) OVER (PARTITION BY vehicle_id ORDER BY time) prev FROM ff),
     st AS (SELECT * FROM ch WHERE status IS DISTINCT FROM prev AND status IS NOT NULL)
SELECT vehicle_id, city, status, prev, time t0, lead(time) OVER (PARTITION BY vehicle_id ORDER BY time) t1,
       lat, lon, charge, discounted, damage_count
FROM st""")
c.execute(f"""
COPY (
  SELECT s.vehicle_id, s.city, s.t0 ride_end_utc, date_diff('second', s.t0, s.t1) / 3600.0 idle_h,
         s.lat, s.lon, s.charge, s.discounted::INT discounted, s.damage_count,
         v.model, v.size_class, v.electric::INT electric
  FROM seg s LEFT JOIN '{D}tables/vehicles.parquet' v USING (vehicle_id)
  WHERE s.status = 'DEPLOYED_FOR_RENTAL' AND s.prev IN ('USER_IN_RIDE', 'PAUSED_BY_USER')
    AND s.t1 IS NOT NULL AND s.t0 >= '2024-06-03' AND s.t0 < '2024-07-01' AND s.lat IS NOT NULL
) TO '{OUT}' (FORMAT parquet)""")
print(c.sql(f"SELECT city, count(*) n, round(avg((idle_h > 12)::INT), 3) stranded, round(median(idle_h), 2) med_idle FROM '{OUT}' GROUP BY 1 ORDER BY 2 DESC").fetchall())
