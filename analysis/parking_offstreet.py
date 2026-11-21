"""Are '>20 m from legal street parking' parks really suspicious, or just in private/off-street car parks?
Uses the local BBBike Berlin OSM extract: amenity=parking (areas + nodes), building=parking/garages, landuse=garages,
amenity=fuel, parking=*  -> off-street parking footprint. Then re-measures the tow-proxy lift on the remainder.
"""
import osmium, shapely, numpy as np, pandas as pd
from shapely.geometry import Point
from pyproj import Transformer

tr = Transformer.from_crs(4326, 25833, always_xy=True)
wkb = osmium.geom.WKBFactory()

class H(osmium.SimpleHandler):
    def __init__(s):
        super().__init__(); s.polys = []; s.pts = []
    def want(s, t):
        return (t.get("amenity") in ("parking", "fuel", "car_rental", "car_sharing", "charging_station", "parking_space")
                or t.get("building") in ("parking", "garages", "garage", "carport") or t.get("landuse") == "garages"
                or t.get("parking") in ("surface", "multi-storey", "underground", "rooftop", "carports", "garage_boxes"))
    def area(s, a):
        if s.want(a.tags):
            try: s.polys.append(shapely.from_wkb(wkb.create_multipolygon(a)))
            except Exception: pass
    def node(s, n):
        if s.want(n.tags):
            s.pts.append((n.location.lon, n.location.lat))

h = H(); h.apply_file("/Users/linusbolls/projects/vorfahrt/data/osm/Berlin.osm.pbf", locations=True)
proj = lambda g: shapely.transform(g, lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1])))
geoms = [proj(g) for g in h.polys] + [shapely.buffer(shapely.points(*tr.transform(x, y)), 25) for x, y in h.pts]
offstreet = shapely.union_all([shapely.buffer(g, 10) for g in geoms])  # 10 m tolerance for GPS
print(f"off-street parking features: {len(h.polys)} areas, {len(h.pts)} nodes")

df = pd.read_parquet("/Users/linusbolls/projects/vorfahrt/miles-ops/analysis/parks_outcomes_berlin_2024-06.parquet")
x, y = tr.transform(df.longitude.values, df.latitude.values)
df["offstreet"] = shapely.contains_xy(offstreet, x, y)
df.to_parquet("/Users/linusbolls/projects/vorfahrt/miles-ops/analysis/parks_outcomes_berlin_2024-06.parquet", index=False)
base = df[(df.bucket == "5 legal")]
g = df.groupby(["bucket", "offstreet"]).agg(parks=("vehicle_id", "size"), tow_proxy_pct=("tow_proxy", lambda s: round(100 * s.mean(), 2)),
        ops_next_pct=("ops_next", lambda s: round(100 * s.mean(), 2)), median_idle_h=("parked_hours", "median"))
g["tow_lift_vs_legal"] = (g.tow_proxy_pct / (100 * base.tow_proxy.mean())).round(2)
print(g.to_string())
sus = df[df.bucket.str.startswith("3") & ~df.offstreet]
days = 28
print(f"\ninner-ring parks >20 m from legal street parking AND not in an off-street car park: {len(sus):,} ({len(sus)/days:.0f}/day)")
sus = sus.copy()
sus["cell"] = (sus.latitude / 0.000225).round().astype(int).astype(str) + "_" + (sus.longitude / 0.00037).round().astype(int).astype(str)
top = sus.groupby("cell").agg(n=("vehicle_id", "size"), lat=("latitude", "median"), lon=("longitude", "median"),
        dist=("dist_to_legal_parking_m", "median"), tow=("tow_proxy", "mean")).sort_values("n", ascending=False).head(15)
print("\ntop suspicious hotspots (25 m cells):"); print(top.round(5).to_string())
