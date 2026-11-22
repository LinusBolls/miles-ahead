"""MILES staff relocations in Berlin, June 3-22 2024, measured from the raw status-change stream.

Input: data/miles/changes/<week>.parquet (Florian's scraper, one row per observed vehicle change).
A relocation = one run of consecutive rows with status IN_RELOCATION_TRIP for a vehicle.
  start t0 = first row of the run; end t1 = first row of the next status run.
  origin  = last position of the previous status run (where the car stood before)
  dest    = first position of the next status run (where it was left)
Also: last customer ride end before the relocation (delay), and the first customer booking/ride after it
(wait at the destination), censored at 2024-06-23 00:00 Berlin (status data breaks from June 24).

Output: miles-ops/analysis/relocations_berlin_2024-06.parquet + printed summary.
Usage: uv run --with duckdb --with pandas --with pyarrow --with numpy python miles-ops/analysis/relocations_june.py
"""
import os
import duckdb, numpy as np, pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WEEKS = ["2024-05-27", "2024-06-03", "2024-06-10", "2024-06-17"]
FILES = [os.path.join(ROOT, "data/miles/changes", f"{w}.parquet") for w in WEEKS]
OUT = os.path.join(ROOT, "miles-ops/analysis/relocations_berlin_2024-06.parquet")
TZ = "Europe/Berlin"
START, END = pd.Timestamp("2024-06-03", tz=TZ), pd.Timestamp("2024-06-23", tz=TZ)
CENSOR = END
OPS = ("IN_OPS", "IN_RELOCATION_TRIP", "IN_FIELD_REPAIR", "IN_LOGISTICS", "IN_EXTERNAL_OPS", "IN_REPAIR", "IN_CLAIMS")

c = duckdb.connect()
c.execute(f"""CREATE TABLE r AS SELECT time, vehicle_id, status, latitude lat, longitude lon, charge
              FROM read_parquet({FILES!r}) WHERE city='BER' AND latitude IS NOT NULL""")
# status runs
c.execute("""CREATE TABLE seg AS
WITH x AS (SELECT *, CASE WHEN status IS DISTINCT FROM lag(status) OVER w THEN 1 ELSE 0 END nb
           FROM r WINDOW w AS (PARTITION BY vehicle_id ORDER BY time)),
     y AS (SELECT *, sum(nb) OVER (PARTITION BY vehicle_id ORDER BY time ROWS UNBOUNDED PRECEDING) sid FROM x)
SELECT vehicle_id, sid, any_value(status) status, min(time) t0,
       arg_min(lat, time) lat0, arg_min(lon, time) lon0, arg_max(lat, time) latL, arg_max(lon, time) lonL,
       arg_min(charge, time) ch0, count(*) n
FROM y GROUP BY vehicle_id, sid""")
c.execute("""CREATE TABLE seg2 AS SELECT *,
  lead(t0) OVER w t1, lead(status) OVER w next_status, lead(lat0) OVER w nlat, lead(lon0) OVER w nlon,
  lag(status) OVER w prev_status, lag(latL) OVER w plat, lag(lonL) OVER w plon, lag(t0) OVER w prev_t0
FROM seg WINDOW w AS (PARTITION BY vehicle_id ORDER BY sid)""")
s = c.execute("SELECT * FROM seg2").df()
s["t0"] = pd.to_datetime(s.t0).dt.tz_localize("UTC").dt.tz_convert(TZ)
s["t1"] = pd.to_datetime(s.t1).dt.tz_localize("UTC").dt.tz_convert(TZ)
s = s.sort_values(["vehicle_id", "t0"]).reset_index(drop=True)


def hav(la0, lo0, la1, lo1):
    la0, lo0, la1, lo1 = map(np.radians, (la0, lo0, la1, lo1))
    a = np.sin((la1 - la0) / 2) ** 2 + np.cos(la0) * np.cos(la1) * np.sin((lo1 - lo0) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


rel = s[(s.status == "IN_RELOCATION_TRIP") & (s.t0 >= START) & (s.t0 < END)].copy()
rel["dur_min"] = (rel.t1 - rel.t0).dt.total_seconds() / 60
rel["olat"] = rel.plat.fillna(rel.lat0); rel["olon"] = rel.plon.fillna(rel.lon0)
rel["dlat"] = rel.nlat; rel["dlon"] = rel.nlon
rel["km"] = hav(rel.olat, rel.olon, rel.dlat, rel.dlon)

# last customer ride end before, first customer booking/ride start after (per vehicle, via merge_asof)
cust_end = s[s.status.isin(["USER_IN_RIDE", "PAUSED_BY_USER"]) & s.t1.notna()][["vehicle_id", "t1"]].rename(columns={"t1": "ride_end"})
cust_start = s[s.status.isin(["USER_IN_RIDE", "BOOKED_BY_USER"])][["vehicle_id", "t0"]].rename(columns={"t0": "next_rent"})
rel = rel.sort_values("t0")
rel = pd.merge_asof(rel, cust_end.sort_values("ride_end"), left_on="t0", right_on="ride_end", by="vehicle_id", direction="backward")
rel = rel.sort_values("t1")
rel = pd.merge_asof(rel.dropna(subset=["t1"]), cust_start.sort_values("next_rent"), left_on="t1", right_on="next_rent",
                    by="vehicle_id", direction="forward")
rel["delay_h"] = (rel.t0 - rel.ride_end).dt.total_seconds() / 3600
rel["wait_after_h"] = (rel.next_rent - rel.t1).dt.total_seconds() / 3600
rel["censored"] = rel.next_rent.isna() | (rel.next_rent > CENSOR)
rel.loc[rel.censored, "wait_after_h"] = ((CENSOR - rel.t1).dt.total_seconds() / 3600)[rel.censored]
rel["hour"] = rel.t0.dt.hour
rel["dc_o"] = np.hypot((rel.olat - 52.52) * 111, (rel.olon - 13.405) * 68)
rel["dc_d"] = np.hypot((rel.dlat - 52.52) * 111, (rel.dlon - 13.405) * 68)
# chaining proxy: another relocation starts within 1.5 km of this one's drop-off within 60 min
rr = rel.sort_values("t0").reset_index(drop=True)
t0s = rr.t0.values.astype("datetime64[s]").astype(np.int64); t1s = rr.t1.values.astype("datetime64[s]").astype(np.int64)
chained = np.zeros(len(rr), bool)
for i in range(len(rr)):
    j = np.where((t0s > t1s[i]) & (t0s <= t1s[i] + 3600))[0]
    if len(j):
        d = hav(rr.dlat[i], rr.dlon[i], rr.olat.values[j], rr.olon.values[j])
        chained[i] = (d <= 1.5).any()
rr["chain_next"] = chained
rel = rr
cols = ["vehicle_id", "t0", "t1", "dur_min", "olat", "olon", "dlat", "dlon", "km", "dc_o", "dc_d", "ride_end", "delay_h",
        "next_rent", "wait_after_h", "censored", "hour", "prev_status", "next_status", "ch0", "chain_next"]
rel[cols].to_parquet(OUT, index=False)

days = (END - START).days
q = lambda x: np.round(np.nanpercentile(x, [10, 25, 50, 75, 90]), 2).tolist()
print(f"relocations (IN_RELOCATION_TRIP runs) {START.date()}..{END.date()} excl: {len(rel)} = {len(rel)/days:.0f}/day")
print("per day:", rel.groupby(rel.t0.dt.date).size().describe().round(0).to_dict())
print("duration min p10/25/50/75/90:", q(rel.dur_min))
print("straight-line km p10/25/50/75/90:", q(rel.km), " share <0.3 km:", round((rel.km < 0.3).mean(), 3))
print("delay since last customer ride h p10/25/50/75/90:", q(rel.delay_h), " mean", round(rel.delay_h.mean(), 1))
print("share delay>12h:", round((rel.delay_h > 12).mean(), 3), " >24h:", round((rel.delay_h > 24).mean(), 3))
print("prev status:", rel.prev_status.value_counts().head(6).to_dict())
print("next status:", rel.next_status.value_counts().head(6).to_dict())
print("start hour histogram:", rel.hour.value_counts().sort_index().to_dict())
print("dist from centre origin p50", round(rel.dc_o.median(), 2), " dest p50", round(rel.dc_d.median(), 2),
      " share moved inward (dest closer by >1 km):", round((rel.dc_o - rel.dc_d > 1).mean(), 3))
unc = rel[~rel.censored]
print("wait after reloc to next customer rental h (uncensored n=%d) p10/25/50/75/90:" % len(unc), q(unc.wait_after_h),
      " censored share", round(rel.censored.mean(), 3))
print("chained (next reloc starts <=1.5 km from drop-off within 60 min):", round(rel.chain_next.mean(), 3))
