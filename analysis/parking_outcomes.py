"""How strong is the parking signal? Berlin, June 2024 parking periods after customer rides.
Joins parks_berlin_2024-06.parquet (area types from Berlin's street-parking map) with segment outcomes:
 - active violation: restriction time window overlaps the parked interval
 - moved_without_ride: car displaced 150 m-3 km while parked & rentable, fuel not lower (tow / Umsetzung proxy)
 - ops_next: next status is an ops/repair status
 - damage_at_park: damage_count increment while parked (reported right after the ride that ended here)
"""
import re, sys
import duckdb, numpy as np, pandas as pd

DB = sys.argv[1]
PARKS = "/Users/linusbolls/projects/vorfahrt/data/berlin_parking/parks_berlin_2024-06.parquet"
c = duckdb.connect(DB, read_only=True)
OPS = "('IN_OPS','IN_RELOCATION_TRIP','IN_FIELD_REPAIR','IN_LOGISTICS','IN_EXTERNAL_OPS','IN_REPAIR','IN_CLAIMS')"
c.execute(f"""CREATE TEMP TABLE outc AS
WITH dmg AS (
  SELECT vehicle_id, seg, count(*) n_dmg FROM (
    SELECT vehicle_id, seg, damage_count, lag(damage_count IGNORE NULLS) OVER (PARTITION BY vehicle_id ORDER BY time) pd FROM r2)
  WHERE damage_count > pd GROUP BY ALL)
SELECT s.vehicle_id, s.t0, s.seg, s.next_status, s.n_fix, s.ch0, s.ch1,
  2*6371000*asin(sqrt(pow(sin(radians(s.lat1-s.lat0)/2),2)+cos(radians(s.lat0))*cos(radians(s.lat1))*pow(sin(radians(s.lon1-s.lon0)/2),2))) moved_m,
  s.next_status IN {OPS} ops_next, coalesce(d.n_dmg, 0) > 0 damage_at_park,
  (SELECT 1) one
FROM seg s LEFT JOIN dmg d USING (vehicle_id, seg)
WHERE s.status='DEPLOYED_FOR_RENTAL' AND s.prev_status IN ('USER_IN_RIDE','PAUSED_BY_USER') AND s.t1 IS NOT NULL""")
outc = c.execute("SELECT * FROM outc").df()
parks = pd.read_parquet(PARKS)
df = parks.merge(outc, left_on=["vehicle_id", "parked_from_utc"], right_on=["vehicle_id", "t0"], how="left")

# --- restriction time windows ---------------------------------------------------------------
DAYS = {"Mo": 0, "Di": 1, "Mi": 2, "Do": 3, "Fr": 4, "Sa": 5, "So": 6}
def parse(s):
    """'Mo-Fr 07:00-17:00 Uhr, Sa 09:00-18:00 Uhr' -> list of (weekday set, start_h, end_h). '' -> always."""
    if not isinstance(s, str) or not s.strip():
        return None
    out = []
    for part in re.split(r"[,;/]", s):
        m = re.search(r"(Mo|Di|Mi|Do|Fr|Sa|So)(?:\s*-\s*(Mo|Di|Mi|Do|Fr|Sa|So))?\s*(\d{1,2})(?::(\d\d))?\s*-\s*(\d{1,2})(?::(\d\d))?", part)
        if not m:
            continue
        d0 = DAYS[m.group(1)]; d1 = DAYS[m.group(2)] if m.group(2) else d0
        days = set(range(d0, d1 + 1)) if d0 <= d1 else set(range(d0, 7)) | set(range(0, d1 + 1))
        out.append((days, int(m.group(3)) + int(m.group(4) or 0) / 60, int(m.group(5)) + int(m.group(6) or 0) / 60))
    return out or "unparsed"

def active_hours(start_local, hours, windows):
    if windows is None:
        return min(hours, 72.0)
    if windows == "unparsed":
        return np.nan
    tot, t, end = 0.0, start_local, start_local + pd.Timedelta(hours=min(hours, 72))
    step = pd.Timedelta(minutes=15)
    while t < end:
        h = t.hour + t.minute / 60
        if any(t.weekday() in d and a <= h < b for d, a, b in windows):
            tot += 0.25
        t += step
    return tot

df["parked_local"] = df.parked_from_utc.dt.tz_localize("UTC").dt.tz_convert("Europe/Berlin")
restr = df.area_type.isin(["no_stopping", "loading_zone", "bus_lane", "taxi_stand"])
df["violation_h"] = 0.0
sub = df[restr]
df.loc[restr, "violation_h"] = [active_hours(t, h, parse(w)) for t, h, w in zip(sub.parked_local, sub.parked_hours, sub.restriction_hours)]
df["active_violation"] = restr & (df.violation_h > 0)
df["tow_proxy"] = (df.moved_m.between(150, 3000)) & (df.ch1 >= df.ch0) & (df.n_fix >= 2)

def bucket(r):
    if r.active_violation: return "1 restricted, restriction ACTIVE while parked"
    if r.area_type in ("no_stopping", "loading_zone", "bus_lane", "taxi_stand"): return "2 restricted, but outside restriction hours"
    if r.area_type == "no_legal_parking_nearby": return "3 >20 m from any legal spot (inner ring)"
    if r.area_type == "no_legal_parking_nearby_outer": return "4 >20 m from legal spot (outer, low precision)"
    return "5 legal"
df["bucket"] = [bucket(r) for r in df.itertuples()]
base = df[df.bucket == "5 legal"]
summ = df.groupby("bucket").agg(parks=("vehicle_id", "size"), median_idle_h=("parked_hours", "median"),
    tow_proxy_pct=("tow_proxy", lambda s: 100 * s.mean()), ops_next_pct=("ops_next", lambda s: 100 * s.mean()),
    damage_pct=("damage_at_park", lambda s: 100 * s.mean()), active_viol_h=("violation_h", "sum")).round(2)
for col, src in [("tow_proxy_pct", "tow_proxy"), ("ops_next_pct", "ops_next"), ("damage_pct", "damage_at_park")]:
    summ[col.replace("_pct", "_lift")] = (summ[col] / (100 * base[src].mean())).round(2)
pd.set_option("display.width", 250)
print(summ.to_string())
print("\nunparsed restriction windows:", int(df.loc[restr, "violation_h"].isna().sum()), "of", int(restr.sum()))

# per-day volumes (live cadence for Berlin)
days = df.parked_local.dt.date.nunique()
print(f"\nper day in Berlin: active violations {df.active_violation.sum()/days:.0f}, >20 m inner {(df.bucket.str.startswith('3')).sum()/days:.0f}, all parks {len(df)/days:.0f}")
# by hour of day for active violations
print("\nactive violations by local hour (share):")
print((df[df.active_violation].parked_local.dt.hour.value_counts(normalize=True).sort_index() * 100).round(1).to_string())
# concentration: do violations repeat at the same spots? (~25 m grid)
v = df[df.active_violation | df.bucket.str.startswith("3")].copy()
v["cell"] = (v.latitude / 0.000225).round().astype(int).astype(str) + "_" + (v.longitude / 0.00037).round().astype(int).astype(str)
cc = v.cell.value_counts()
print(f"\nhotspots (25 m cells, violations + >20m): {len(v)} parks in {len(cc)} cells; top 50 cells = {100*cc.head(50).sum()/len(v):.1f}%, top 200 = {100*cc.head(200).sum()/len(v):.1f}%; cells with >=10 parks: {(cc>=10).sum()}")
# repeat vehicles? (not users - we have no users)  damage by distance bins
df["dist_bin"] = pd.cut(df.dist_to_legal_parking_m.fillna(0), [-1, 5, 10, 20, 40, 80, 1e9], labels=["<5", "5-10", "10-20", "20-40", "40-80", ">80"])
print("\nby distance to legal parking (inner ring only):")
print(df[df.inside_sbahn_ring].groupby("dist_bin", observed=True).agg(parks=("vehicle_id", "size"),
      tow_proxy_pct=("tow_proxy", lambda s: round(100 * s.mean(), 2)), ops_next_pct=("ops_next", lambda s: round(100 * s.mean(), 2)),
      damage_pct=("damage_at_park", lambda s: round(100 * s.mean(), 3)), median_idle_h=("parked_hours", "median")).to_string())
df.drop(columns=["parked_local"]).to_parquet("/Users/linusbolls/projects/vorfahrt/miles-ops/analysis/parks_outcomes_berlin_2024-06.parquet", index=False)
