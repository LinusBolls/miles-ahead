"""Build the demo vehicle feed for the MILES x Rescue concept app (web PWA + iOS).

Source: miles-ops/backend/geo/replay_berlin_2024-06.parquet — the June 2024 Berlin replay (real parked positions from
the MILES open fleet data) with `p_tabpfn` = TabPFN P(idle > 12 h after the ride end), scored OUT-OF-SAMPLE
(June 17-22 rows use the June 3-16 context). Nothing here calls a model; the scores are precomputed.

Output (one snapshot, Tue 18 Jun 2024 21:00 Berlin):
  src/data/vehicles.json   bundled fallback (offline)
  (copy to public/api/vehicles.json for the PWA; scripts/build_web does that)

Fleet  = every car parked at the snapshot within RADIUS_M of CIC Berlin.
Rescue = p_tabpfn >= 0.4556 (the replay's top-10% threshold) AND parked < 12 h ago (still a prediction, not observed).
Destination ("value map") = the 1 km cell (Carolina's grid indexing) within 0.6-2.5 km of the car with the lowest
observed median idle time for weekday 19-23 h ride ends, June 3-22 2024 (>= 15 events), computed separately for vans (size L/X) and cars. Observed, not modelled.

Run: miles-ops/backend/.venv/bin/python scripts/build_rescue_data.py
"""
import json, math, os
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SRC = os.path.join(ROOT, "..", "miles-ops", "backend", "geo", "replay_berlin_2024-06.parquet")
OUT = os.path.join(ROOT, "src", "data", "vehicles.json")

SNAP_LOCAL = pd.Timestamp("2024-06-18 21:00", tz="Europe/Berlin")
SNAP = SNAP_LOCAL.tz_convert("UTC").tz_localize(None)
CIC = (52.49373, 13.44611)
RADIUS_M = 4500
THR = 0.4556
KM_PRICE = {"S": 0.98, "M": 0.98, "P": 1.29, "L": 1.29, "X": 1.29}  # same assumption as miles-drive/app.py
UNLOCK = {"S": 1.0, "M": 1.0, "P": 2.0, "L": 2.0, "X": 2.0}

PLACES = [
    ("Görlitzer Park", 52.4965, 13.4370), ("Kottbusser Tor", 52.4991, 13.4180), ("Schlesisches Tor", 52.5010, 13.4419),
    ("Warschauer Straße", 52.5058, 13.4492), ("Ostkreuz", 52.5030, 13.4690), ("Treptower Park", 52.4934, 13.4614),
    ("Hermannplatz", 52.4868, 13.4245), ("Boxhagener Platz", 52.5105, 13.4597), ("Frankfurter Tor", 52.5158, 13.4541),
    ("Moritzplatz", 52.5036, 13.4108), ("Mehringdamm", 52.4935, 13.3880), ("Südstern", 52.4890, 13.4075),
    ("Rathaus Neukölln", 52.4815, 13.4350), ("S Neukölln", 52.4694, 13.4422), ("S Sonnenallee", 52.4728, 13.4554),
    ("Plänterwald", 52.4785, 13.4740), ("Weichselplatz", 52.4870, 13.4510), ("Alexanderplatz", 52.5219, 13.4132),
    ("Jannowitzbrücke", 52.5150, 13.4180), ("Ostbahnhof", 52.5103, 13.4348), ("Strausberger Platz", 52.5180, 13.4290),
    ("Samariterstraße", 52.5145, 13.4648), ("Rummelsburg", 52.4993, 13.4785), ("Hallesches Tor", 52.4977, 13.3913),
    ("Gneisenaustraße", 52.4913, 13.3956), ("Boddinstraße", 52.4797, 13.4255), ("Schönleinstraße", 52.4934, 13.4224),
    ("Frankfurter Allee", 52.5135, 13.4750), ("Baumschulenweg", 52.4670, 13.4890), ("Oberschöneweide", 52.4610, 13.5160),
    ("Lichtenberg", 52.5100, 13.4970), ("Tempelhof", 52.4703, 13.3858), ("Hermannstraße", 52.4672, 13.4310),
    ("Wühlischplatz", 52.5075, 13.4655), ("Lausitzer Platz", 52.4995, 13.4300), ("Reuterplatz", 52.4890, 13.4330),
]


def place(lat, lon):
    return min(PLACES, key=lambda p: (p[1] - lat) ** 2 + ((p[2] - lon) * 0.61) ** 2)[0]


def dist_m(a, b, c, d):
    return math.hypot((a - c) * 111_000, (b - d) * 68_000)


def cell(lat, lon):
    return math.floor((lon - 13.405) * 68), math.floor((lat - 52.52) * 111)


def cell_center(cx, cy):
    return 52.52 + (cy + 0.5) / 111, 13.405 + (cx + 0.5) / 68


df = pd.read_parquet(SRC)
df["end"] = df.parked_from_utc + pd.to_timedelta(df.parked_hours, unit="h")

# --- value map: observed median idle per 1 km cell, weekday evenings ---
loc = df.parked_from_utc.dt.tz_localize("UTC").dt.tz_convert("Europe/Berlin")
ev = df[(loc.dt.day_of_week < 5) & (loc.dt.hour >= 19) & (loc.dt.hour <= 23)].copy()
ev["cx"] = np.floor((ev.longitude - 13.405) * 68).astype(int)
ev["cy"] = np.floor((ev.latitude - 52.52) * 111).astype(int)
ev["van"] = ev.size_class.isin(["L", "X"])
VMS = {}
for van, part in ev.groupby("van"):  # vans and cars rent differently: separate value maps
    g = part.groupby(["cx", "cy"]).parked_hours.agg(["median", "count"]).reset_index()
    VMS[bool(van)] = {(int(a), int(b)): (float(m), int(n)) for a, b, m, n in g[["cx", "cy", "median", "count"]].itertuples(index=False)}
MIN_N = 15

# --- snapshot ---
s = df[(df.parked_from_utc <= SNAP) & (df.end > SNAP)].sort_values("parked_from_utc").drop_duplicates("vehicle_id", keep="last")
s = s[[dist_m(a, b, *CIC) <= RADIUS_M for a, b in zip(s.latitude, s.longitude)]]

vehicles = []
for r in s.itertuples():
    parked_h = (SNAP - r.parked_from_utc).total_seconds() / 3600
    p = float(r.p_tabpfn)
    rescue = p >= THR and parked_h < 12
    v = {
        "id": int(r.vehicle_id), "lat": round(float(r.latitude), 6), "lon": round(float(r.longitude), 6),
        "model": r.model, "plate": r.plate, "size": r.size_class, "ev": bool(r.electric), "pct": int(r.ch1),
        "kmPrice": KM_PRICE.get(r.size_class, 0.98), "unlock": UNLOCK.get(r.size_class, 1.0),
        "parkedH": round(parked_h, 1),
    }
    if rescue:
        VM = VMS[r.size_class in ("L", "X")]
        here = VM.get(cell(r.latitude, r.longitude))
        best = None
        for (cx, cy), (med, n) in VM.items():
            if n < MIN_N:
                continue
            clat, clon = cell_center(cx, cy)
            m = dist_m(r.latitude, r.longitude, clat, clon)
            if 600 <= m <= 2500:
                key = med + 0.8 * m / 1000
                if best is None or key < best[0]:
                    best = (key, clat, clon, med, m)
        v["rescue"] = {
            "p": round(p, 3),
            "area": place(r.latitude, r.longitude),
            "waitHereH": round(here[0], 1) if here and here[1] >= MIN_N else None,
            "dest": None if best is None else {
                "name": place(best[1], best[2]), "lat": round(best[1], 5), "lon": round(best[2], 5),
                "waitH": round(best[3], 1), "m": int(best[4]),
            },
        }
    vehicles.append(v)

doc = {
    "meta": {
        "source": "June 2024 Berlin replay (MILES open fleet data)",
        "snapshot": "Tue 18 Jun 2024, 21:00",
        "snapshotIso": SNAP_LOCAL.isoformat(),
        "model": "TabPFN P(idle > 12 h), precomputed out-of-sample",
        "rescueRule": f"p_tabpfn >= {THR} (top 10% of replay ride ends) and parked < 12 h",
        "valueMap": "observed median idle per 1 km cell, weekday 19-23 h ride ends, June 3-22 2024",
        "demo": True,
        "center": {"lat": CIC[0], "lon": CIC[1], "name": "CIC Berlin"},
    },
    "vehicles": vehicles,
    "demoPosition": {"lat": 52.4870, "lon": 13.4625, "name": "Elsenstraße, Treptow"},
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
res = [v for v in vehicles if "rescue" in v]
print(f"{len(vehicles)} cars, {len(res)} rescue, {os.path.getsize(OUT)//1024} KB -> {OUT}")
D = (52.4870, 13.4625)
for v in sorted(res, key=lambda v: dist_m(v["lat"], v["lon"], *D))[:10]:
    print(int(dist_m(v["lat"], v["lon"], *D)), v["model"], v["parkedH"], v["rescue"])
