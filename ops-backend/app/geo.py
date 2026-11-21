"""Berlin parking classifier: same logic as data/berlin_parking/parking_enrich.py + parking_offstreet.py,
on the compact preprocessed geometry in geo/berlin_geo.pkl.gz (EPSG:25833)."""
import gzip, pickle
import numpy as np, shapely
from pyproj import Transformer

RESTRICTED_AREAS = ("no_stopping", "loading_zone", "bus_lane", "taxi_stand")
REASON_AREA = {"Ladezone": "loading_zone", "Bussonderfahrstreifen": "bus_lane", "Taxi": "taxi_stand"}


class BerlinGeo:
    SG = 60.0  # street-name grid (m)

    def _street(self, x, y):
        gx, gy = int(np.floor(x / self.SG)), int(np.floor(y / self.SG))
        best, bd = -1, 1e18
        for r in (1, 2):
            for ix in range(gx - r, gx + r + 1):
                k = ix * 1000000
                a = np.searchsorted(self.s_key, k + gy - r, "left"); b = np.searchsorted(self.s_key, k + gy + r, "right")
                if b > a:
                    dd = (self.s_x[a:b] - x) ** 2 + (self.s_y[a:b] - y) ** 2
                    j = int(np.argmin(dd))
                    if dd[j] < bd:
                        bd, best = float(dd[j]), a + j
            if best >= 0:
                break
        return self.streets[self.s_street[best]] if best >= 0 else ""

    def __init__(self, path):
        d = pickle.load(gzip.open(path))
        self.tr = Transformer.from_crs(4326, 25833, always_xy=True)
        self.legal = shapely.from_wkb(d["legal_tiles_wkb"])  # legal polygons unioned per 400 m tile
        self.legal_street = d["legal_street"]
        cx, cy = d["legal_cx"], d["legal_cy"]
        gx, gy = np.floor(cx / self.SG).astype(np.int64), np.floor(cy / self.SG).astype(np.int64)
        key = gx * 1000000 + gy
        o = np.argsort(key, kind="stable")
        self.s_key, self.s_x, self.s_y, self.s_street = key[o], cx[o], cy[o], self.legal_street[o]
        self.res = shapely.from_wkb(d["res_wkb"])
        self.res_type, self.res_reason, self.res_hours = d["res_type"], d["res_reason"], d["res_hours"]
        self.res_street = d["res_street"]
        self.streets = d["streets"]
        self.ring = shapely.from_wkb(d["ring_wkb"]); shapely.prepare(self.ring)
        self.zones = shapely.from_wkb(d["zones_wkb"])
        self.zone_name, self.zone_fee, self.zone_hours = d["zone_name"], d["zone_fee"], d["zone_hours"]
        # off-street footprint as parts + STRtree (a prepared 1.1M-vertex union costs ~100 MB)
        self.offstreet = shapely.get_parts(shapely.from_wkb(d["offstreet_wkb"]))
        self.t_off = shapely.STRtree(self.offstreet)
        self.t_legal = shapely.STRtree(self.legal)
        self.t_res = shapely.STRtree(self.res)
        self.t_zone = shapely.STRtree(self.zones)
        del d

    def classify(self, lats, lons):
        """Vectorised. Returns a list of dicts (one per point)."""
        lats = np.asarray(lats, float); lons = np.asarray(lons, float)
        n = len(lats)
        if n == 0:
            return []
        x, y = self.tr.transform(lons, lats)
        pts = shapely.points(x, y)
        in_ring = shapely.contains_xy(self.ring, x, y)
        off = np.zeros(n, bool)
        oh = self.t_off.query(pts, predicate="intersects")[0]
        off[oh] = True
        (pi, ti), dist = self.t_legal.query_nearest(pts, return_distance=True, all_matches=False)
        d_legal = np.full(n, np.nan); d_legal[pi] = dist
        street = [self._street(x[i], y[i]) for i in range(n)]
        res_idx = [-1] * n
        hp, ht = self.t_res.query(pts, predicate="intersects")
        for a, b in zip(hp, ht):  # last hit wins (same as the pandas .loc assignment in parking_enrich.py)
            res_idx[a] = b
        zone_idx = [-1] * n
        zp, zt = self.t_zone.query(pts, predicate="intersects")
        for a, b in zip(zp, zt):
            zone_idx[a] = b
        out = []
        for i in range(n):
            r = res_idx[i]
            if r >= 0:
                reason = self.res_reason[r] or "Haltverbot (other)"
                area = REASON_AREA.get(reason.split(";")[0], "no_stopping")
                st = self.streets[self.res_street[r]] or street[i]
            else:
                reason = ""
                dl = d_legal[i]
                if in_ring[i]:
                    area = "legal" if dl <= 20 else "no_legal_parking_nearby"
                else:
                    area = "legal" if dl <= 20 else "no_legal_parking_nearby_outer"
                st = street[i]
            z = zone_idx[i]
            out.append(dict(
                area_type=area, inside_sbahn_ring=bool(in_ring[i]), offstreet=bool(off[i]),
                dist_to_legal_m=None if np.isnan(d_legal[i]) else round(float(d_legal[i]), 1),
                street=st,
                restriction_type=self.res_type[r] if r >= 0 else "",
                restriction_reason=reason,
                restriction_hours=self.res_hours[r] if r >= 0 else "",
                paid_zone=self.zone_name[z] if z >= 0 else "",
                paid_zone_fee_eur_h=self.zone_fee[z] if z >= 0 else None,
                paid_zone_hours=self.zone_hours[z] if z >= 0 else "",
            ))
        return out
