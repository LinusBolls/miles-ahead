"""Preprocess Berlin parking geodata into compact files in backend/geo/ (run locally, not in the container).

Same logic as data/berlin_parking/parking_enrich.py + miles-ops/analysis/parking_offstreet.py:
  legal      = inner sections with empty `beschraenkung` + all outer sections (EPSG:25833 polygons)
  restricted = inner sections with `beschraenkung` set (+ reason, hours, street)
  ring       = concave hull of inner-section centroids (S-Bahn ring proxy)
  zones      = paid-parking zones (+ "<bezirk> <parkzone>", fee EUR/h, hours)
  offstreet  = OSM off-street parking footprint (+10 m GPS tolerance)
Output: geo/berlin_geo.pkl.gz (WKB arrays + props) and geo/paid_zones.geojson (simplified WGS84, for the API).
"""
import os as _os
_REPO = _os.environ.get("MILES_REPO", _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../.."))) + "/"  # repo root; raw data goes in data/ (see README)
import gzip, json, pickle, sys, time
import numpy as np, shapely
from shapely.geometry import shape, mapping
from pyproj import Transformer

D = _REPO + "data/berlin_parking"
OSM = _REPO + "data/osm/Berlin.osm.pbf"
OUT = _REPO + "miles-ops/backend/geo"
tr = Transformer.from_crs(4326, 25833, always_xy=True)
proj = lambda g: shapely.transform(g, lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1])))
t0 = time.time()


def load(name):
    feats = json.load(open(f"{D}/{name}.geojson"))["features"]
    geoms = np.array([proj(shape(f["geometry"])) for f in feats], dtype=object)
    return geoms, [f["properties"] for f in feats], feats


inner_g, inner_p, _ = load("street_parking_inner")
outer_g, outer_p, _ = load("street_parking_outer")
zones_g, zones_p, zones_f = load("paid_parking_zones")
print("loaded", len(inner_g), len(outer_g), len(zones_g), f"{time.time()-t0:.0f}s")

legal_mask = np.array([(p.get("beschraenkung") or "") == "" for p in inner_p])
restricted = inner_g[~legal_mask]
res_p = [p for p, m in zip(inner_p, legal_mask) if not m]
legal_all = np.concatenate([inner_g[legal_mask], outer_g])
legal_street = [p.get("strassenname") or "" for p, m in zip(inner_p, legal_mask) if m] + [p.get("strassenname") or "" for p in outer_p]
ring = shapely.concave_hull(shapely.union_all(shapely.centroid(inner_g)), ratio=0.05)


def compact(gs, tol=0.3):
    gs = shapely.simplify(np.asarray(gs, dtype=object), tol, preserve_topology=True)
    gs = shapely.set_precision(gs, 0.1)
    return shapely.to_wkb(gs)


streets = sorted(set(legal_street) | {p.get("strassenname") or "" for p in res_p})
sidx = {s: i for i, s in enumerate(streets)}

# --- off-street parking footprint from OSM ---
import osmium
wkbf = osmium.geom.WKBFactory()


class H(osmium.SimpleHandler):
    def __init__(s):
        super().__init__(); s.polys = []; s.pts = []

    def want(s, t):
        return (t.get("amenity") in ("parking", "fuel", "car_rental", "car_sharing", "charging_station", "parking_space")
                or t.get("building") in ("parking", "garages", "garage", "carport") or t.get("landuse") == "garages"
                or t.get("parking") in ("surface", "multi-storey", "underground", "rooftop", "carports", "garage_boxes"))

    def area(s, a):
        if s.want(a.tags):
            try: s.polys.append(shapely.from_wkb(wkbf.create_multipolygon(a)))
            except Exception: pass

    def node(s, n):
        if s.want(n.tags):
            s.pts.append((n.location.lon, n.location.lat))


h = H(); h.apply_file(OSM, locations=True)
og = [proj(g) for g in h.polys] + [shapely.buffer(shapely.points(*tr.transform(x, y)), 25) for x, y in h.pts]
offstreet = shapely.union_all([shapely.buffer(g, 10) for g in og])
offstreet = shapely.set_precision(shapely.simplify(offstreet, 0.5), 0.1)
print("offstreet", len(h.polys), len(h.pts), f"{time.time()-t0:.0f}s")

import re
fee = []
for p in zones_p:
    m = re.search(r"([\d,]+)", str(p.get("gebuehr") or "")); fee.append(float(m.group(1).replace(",", ".")) if m else None)

data = dict(
    legal_wkb=compact(legal_all), legal_street=np.array([sidx[s] for s in legal_street], dtype=np.int32),
    res_wkb=compact(restricted, 0.1),
    res_type=[p.get("beschraenkung") or "" for p in res_p],
    res_reason=[p.get("grund_fuer_beschraenkung") or "" for p in res_p],
    res_hours=[(p.get("geltungszeit_der_beschraenkung") or "").strip() for p in res_p],
    res_street=np.array([sidx[p.get("strassenname") or ""] for p in res_p], dtype=np.int32),
    streets=streets,
    ring_wkb=shapely.to_wkb(ring),
    zones_wkb=shapely.to_wkb(zones_g),
    zone_name=[f"{p['bezirk']} {p['parkzone']}" for p in zones_p],
    zone_fee=fee, zone_hours=[(p.get("zeiten") or "").strip() for p in zones_p],
    zone_spaces=[p.get("parkstaende") for p in zones_p],
    offstreet_wkb=shapely.to_wkb(offstreet),
)
from geo_compact import compact_legal
data = compact_legal(data)
with gzip.open(f"{OUT}/berlin_geo.pkl.gz", "wb", compresslevel=6) as f:
    pickle.dump(data, f, protocol=5)

feats = []
for f, name, fe, hrs in zip(zones_f, data["zone_name"], fee, data["zone_hours"]):
    g = shapely.set_precision(shapely.simplify(shape(f["geometry"]), 0.00005), 0.000001)
    feats.append({"type": "Feature", "geometry": mapping(g),
                  "properties": {"zone": name, "fee_eur_h": fe, "hours": hrs, "spaces": f["properties"].get("parkstaende")}})
json.dump({"type": "FeatureCollection", "features": feats}, open(f"{OUT}/paid_zones.geojson", "w"), separators=(",", ":"))
print("done", f"{time.time()-t0:.0f}s")
