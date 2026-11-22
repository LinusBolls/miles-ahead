"""Test MILES Berlin June 2024 ride-end parking positions against Berlin's official street-parking map."""
import os as _os
_REPO = _os.environ.get("MILES_REPO", _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../../.."))) + "/"  # repo root; raw data goes in data/ (see README)
import json, sys
import duckdb, numpy as np, pandas as pd, shapely
from shapely.geometry import shape
from pyproj import Transformer

D = _REPO + "data/berlin_parking"
tr = Transformer.from_crs(4326, 25833, always_xy=True)

def load(name, keep=None):
    feats = json.load(open(f"{D}/{name}.geojson"))["features"]
    geoms = [shapely.transform(shape(f["geometry"]), lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1]))) for f in feats]
    props = pd.DataFrame([f["properties"] for f in feats])
    return np.array(geoms, dtype=object), props

inner_g, inner_p = load("street_parking_inner")
outer_g, outer_p = load("street_parking_outer")
zones_g, zones_p = load("paid_parking_zones")
print("loaded", len(inner_g), len(outer_g), len(zones_g))
legal_mask = inner_p["beschraenkung"].fillna("") == ""
restricted = inner_g[~legal_mask.values]
legal_all = np.concatenate([inner_g[legal_mask.values], outer_g])
ring = shapely.concave_hull(shapely.union_all(shapely.centroid(inner_g)), ratio=0.05)

c = duckdb.connect(sys.argv[1], read_only=True)
park = c.execute("""SELECT s.vehicle_id, s.t0, s.dur_h, s.plon, s.plat FROM seg s
  WHERE status='DEPLOYED_FOR_RENTAL' AND prev_status IN ('USER_IN_RIDE','PAUSED_BY_USER') AND t1 IS NOT NULL AND plat IS NOT NULL""").df()
x, y = tr.transform(park.plon.values, park.plat.values)
pts = shapely.points(x, y)
park["in_ring"] = shapely.contains_xy(ring, x, y)

t_legal = shapely.STRtree(legal_all)
idx, dist = t_legal.query_nearest(pts, return_distance=True, all_matches=False)
park["d_legal"] = np.full(len(pts), np.nan); park.loc[park.index[idx[0]], "d_legal"] = dist

t_res = shapely.STRtree(restricted)
hit = t_res.query(pts, predicate="intersects")
res_p = inner_p[~legal_mask.values].reset_index(drop=True)
park["restricted"] = ""
park.loc[park.index[hit[0]], "restricted"] = res_p.loc[hit[1], "grund_fuer_beschraenkung"].fillna("").replace("", "Haltverbot (other)").values

t_z = shapely.STRtree(zones_g)
zh = t_z.query(pts, predicate="intersects")
park["zone_fee"] = np.nan
fee = zones_p["gebuehr"].str.extract(r"([\d,]+)")[0].str.replace(",", ".").astype(float)
park.loc[park.index[zh[0]], "zone_fee"] = fee.loc[zh[1]].values

inner = park[park.in_ring]
print(f"\nride-end parks Berlin June: {len(park):,}; inside S-Bahn ring (inner dataset): {len(inner):,}")
for lim in (5, 10, 20, 40):
    print(f"  > {lim:>2} m from any legal street-parking area: {100*(inner.d_legal > lim).mean():.1f}%")
print("  inside a restricted (Haltverbot) section:", f"{100*(inner.restricted != '').mean():.2f}%")
print(inner[inner.restricted != ""].restricted.value_counts().head(6).to_string())
print(f"\nall Berlin: parks inside paid-parking zones: {100*park.zone_fee.notna().mean():.1f}%")
# rough fee: hours overlapping Mon-Sat 09-20 local, at zone hourly rate
p = park[park.zone_fee.notna()].copy()
t0 = p.t0.dt.tz_localize("UTC").dt.tz_convert("Europe/Berlin")
def billable(start, hours):
    total, t, end = 0.0, start, start + pd.Timedelta(hours=min(hours, 72))
    while t < end:
        nxt = min(end, (t + pd.Timedelta(hours=1)).floor("h"))
        if t.weekday() < 6 and 9 <= t.hour < 20: total += (nxt - t).total_seconds() / 3600
        t = nxt
    return total
p["bill_h"] = [billable(s, h) for s, h in zip(t0, p.dur_h)]
p["fee"] = p.bill_h * p.zone_fee
print(f"  paid-zone parking: {p.bill_h.sum():,.0f} billable hours, ~EUR {p.fee.sum():,.0f} in fees for June (Mon-Sat 9-20 approximation, 72h cap per park)")
print(f"  per car-day: ~EUR {p.fee.sum() / park.vehicle_id.nunique() / 28:.2f}")
