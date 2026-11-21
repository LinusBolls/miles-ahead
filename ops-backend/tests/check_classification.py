"""Classification unit check: classify N random rows of parks_outcomes_berlin_2024-06.parquet with the compact
geodata and compare to the original analysis columns. Exit 1 if any agreement < 95%."""
import os, sys, time
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.geo import BerlinGeo

PARQ = sys.argv[1] if len(sys.argv) > 1 else "/Users/linusbolls/projects/vorfahrt/miles-ops/analysis/parks_outcomes_berlin_2024-06.parquet"
N = int(os.environ.get("N", 600))
t = time.time(); g = BerlinGeo(os.path.join(os.path.dirname(__file__), "..", "geo", "berlin_geo.pkl.gz")); print(f"geo loaded {time.time()-t:.1f}s")
d = pd.read_parquet(PARQ)
rng = np.random.default_rng(42)
# stratify: half random, half from non-legal areas so the rare classes are actually tested
s = pd.concat([d.sample(N // 2, random_state=1), d[d.area_type != "legal"].sample(N // 2, random_state=2)])
t = time.time(); c = pd.DataFrame(g.classify(s.latitude.values, s.longitude.values)); dt = time.time() - t
res = {
    "area_type": (c.area_type.values == s.area_type.values).mean(),
    "paid_zone": (c.paid_zone.values == s.paid_zone.fillna("").values).mean(),
    "dist_to_legal (|diff|<=2 m or both >20 m)": (((c.dist_to_legal_m.astype(float).values - s.dist_to_legal_parking_m.values).__abs__() <= 2)
                                                  | ((c.dist_to_legal_m.astype(float).values > 20) & (s.dist_to_legal_parking_m.values > 20))).mean(),
    "offstreet": (c.offstreet.values == s.offstreet.values).mean(),
    "inside_sbahn_ring": (c.inside_sbahn_ring.values == s.inside_sbahn_ring.values).mean(),
}
print(f"classified {len(s)} rows in {dt*1000:.0f} ms")
for k, v in res.items():
    print(f"  {k:45s} {v:6.1%}")
bad = s[c.area_type.values != s.area_type.values]
if len(bad):
    print("area_type mismatches (orig -> new):")
    print(pd.crosstab(bad.area_type.values, c.area_type.values[c.area_type.values != s.area_type.values]))
ok = all(v >= 0.95 for v in res.values())
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
