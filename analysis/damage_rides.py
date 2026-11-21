"""What predicts a damage report? One row per customer ride ending in Berlin, June 2024.
Label: damage_count increments while the car is parked right after the ride (46% of reports land within 15 min of ride end).
"""
import sys, duckdb, pandas as pd
c = duckdb.connect(sys.argv[1], read_only=True)
veh = pd.read_parquet("/Users/linusbolls/projects/vorfahrt/data/miles/tables/vehicles.parquet")
parks = pd.read_parquet("/Users/linusbolls/projects/vorfahrt/miles-ops/analysis/parks_outcomes_berlin_2024-06.parquet")
c.register("veh", veh); c.register("parks", parks)
rides = c.execute("""
WITH s AS (SELECT vehicle_id, seg, status, t0, t1, dur_h, prev_lat, prev_lon, plat, plon, prev_ch, ch1, prev_dmg, disc_any,
                  lag(status) OVER w ps, lag(t0) OVER w pt0, lag(dur_h) OVER w pdur, lag(status, 2) OVER w ps2, lag(t0, 2) OVER w pt02
           FROM seg WINDOW w AS (PARTITION BY vehicle_id ORDER BY seg))
SELECT s.vehicle_id, s.t0 ride_end, CASE WHEN s.ps='USER_IN_RIDE' THEN s.pt0 WHEN s.ps2='USER_IN_RIDE' THEN s.pt02 END ride_start,
       s.prev_dmg prior_damage, p.damage_at_park damaged, p.area_type end_area, p.dist_to_legal_parking_m end_dist, p.offstreet end_offstreet,
       p.tow_proxy, p.parked_hours, v.model, v.size_class, v.electric, v.first_seen
FROM s JOIN parks p ON p.vehicle_id = s.vehicle_id AND p.parked_from_utc = s.t0 LEFT JOIN veh v ON v.vehicle_id = s.vehicle_id
WHERE s.status='DEPLOYED_FOR_RENTAL' AND s.ps IN ('USER_IN_RIDE','PAUSED_BY_USER')""").df()
rides["start_local"] = pd.to_datetime(rides.ride_start).dt.tz_localize("UTC").dt.tz_convert("Europe/Berlin")
rides["dur_min"] = (pd.to_datetime(rides.ride_end) - pd.to_datetime(rides.ride_start)).dt.total_seconds() / 60
rides = rides[rides.dur_min.between(1, 24 * 60)]
base = rides.damaged.mean()
print(f"rides: {len(rides):,}; damage reports right after: {int(rides.damaged.sum())} ({100*base:.2f}% of rides, {rides.damaged.sum()/28:.0f}/day)")
def lift(col, bins=None, labels=None, top=None):
    s = pd.cut(rides[col], bins, labels=labels) if bins is not None else rides[col]
    g = rides.groupby(s, observed=True).damaged.agg(["size", "sum", "mean"])
    if top: g = g[g["size"] >= top]
    g["lift"] = (g["mean"] / base).round(2); g["pct"] = (100 * g["mean"]).round(3)
    print(f"\n-- {col}"); print(g[["size", "sum", "pct", "lift"]].sort_values("lift", ascending=False).head(12).to_string())
rides["hour"] = rides.start_local.dt.hour
rides["night"] = rides.hour.isin([22, 23, 0, 1, 2, 3, 4])
rides["weekend_night"] = rides.night & rides.start_local.dt.dayofweek.isin([4, 5, 6])
lift("dur_min", [0, 10, 20, 40, 90, 240, 1e9], ["<10", "10-20", "20-40", "40-90", "90-240", ">240"])
lift("hour", [-1, 5, 9, 15, 19, 21, 24], ["0-5", "6-9", "10-15", "16-19", "20-21", "22-23"])
lift("weekend_night")
lift("prior_damage", [-1, 0, 2, 5, 10, 1e9], ["0", "1-2", "3-5", "6-10", ">10"])
lift("size_class"); lift("electric"); lift("model", top=3000)
lift("end_area")
rides.to_parquet("/Users/linusbolls/projects/vorfahrt/miles-ops/analysis/rides_damage_berlin_2024-06.parquet", index=False)
# concentration on vehicles
pv = rides.groupby("vehicle_id").damaged.sum()
print(f"\ncars with >=1 report in June: {(pv>0).sum()} of {len(pv)}; cars with >=3: {(pv>=3).sum()} accounting for {pv[pv>=3].sum()} reports")
