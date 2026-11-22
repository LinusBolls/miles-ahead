"""Extract charging + fuel stations from an OSM PBF into a compact JSON for miles-drive.
Usage: python extract_stations.py Berlin.osm.pbf out.json
Output: {"charge": [[lat, lon, name, operator, maxkw, sockets, partner_hint], ...], "fuel": [[lat, lon, name, brand, partner_hint], ...]}
"""
import json, re, sys
import osmium

CHARGE, FUEL = [], []


def num(s):
    m = re.findall(r"(\d+(?:[.,]\d+)?)\s*(kw|w)?", (s or "").lower())
    best = 0
    for v, unit in m:
        v = float(v.replace(",", "."))
        if unit == "w" or v > 1000:
            v /= 1000
        best = max(best, v)
    return best


def maxkw(tags):
    vals = [num(v) for k, v in tags.items() if "output" in k or k == "charging_station:output" or k.endswith(":power")]
    return round(max(vals), 0) if vals else None


class H(osmium.SimpleHandler):
    def handle(self, tags, lat, lon):
        a = tags.get("amenity")
        if a == "charging_station":
            access = tags.get("access", "")
            if access in ("private", "no", "customers") and tags.get("motorcar") != "yes":
                return
            if tags.get("motorcar") == "no" or (tags.get("bicycle") == "yes" and tags.get("motorcar") not in ("yes",)):
                # bike-only chargers
                if tags.get("motorcar") != "yes" and not any(k.startswith("socket:type2") or k.startswith("socket:ccs") or k.startswith("socket:chademo") for k in tags):
                    return
            sockets = sorted({k.split(":")[1] for k in tags if k.startswith("socket:") and k.count(":") == 1 and tags[k] not in ("0", "no")})
            CHARGE.append([round(lat, 6), round(lon, 6), tags.get("name") or "", tags.get("operator") or tags.get("network") or tags.get("brand") or "",
                           maxkw(dict(tags)), ",".join(sockets)])
        elif a == "fuel":
            if tags.get("access") in ("private", "no"):
                return
            FUEL.append([round(lat, 6), round(lon, 6), tags.get("name") or "", tags.get("brand") or tags.get("operator") or ""])

    def node(self, n):
        if "amenity" in n.tags:
            self.handle({t.k: t.v for t in n.tags}, n.location.lat, n.location.lon)

    def way(self, w):
        if w.tags.get("amenity") in ("charging_station", "fuel"):
            try:
                pts = [(nd.location.lat, nd.location.lon) for nd in w.nodes if nd.location.valid()]
            except Exception:
                return
            if pts:
                self.handle({t.k: t.v for t in w.tags}, sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


h = H()
h.apply_file(sys.argv[1], locations=True)
json.dump({"charge": CHARGE, "fuel": FUEL}, open(sys.argv[2], "w"), ensure_ascii=False, separators=(",", ":"))
print(len(CHARGE), "charging", len(FUEL), "fuel")
