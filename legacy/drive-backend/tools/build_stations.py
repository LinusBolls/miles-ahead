"""stations_raw.json (from extract_stations.py) -> data/stations.json with a partner hint per station.
MILES partner status cannot be read from OSM. What we know (MILES help center, Nov 2026):
  - EV: charging is started in the MILES app via Plugsurfing roaming; partner stations are the blue pins in the app.
    Plugsurfing roams most public German operators, but not Tesla Superchargers. -> public stations of known roaming
    operators = "likely", Tesla = dropped, unknown operator = "unknown".
  - Fuel: refuelling is unlocked in the app ("free of charge throughout Germany"); the article is tagged TOTAL and Aral.
    -> Aral / TotalEnergies = "likely", other brands = "unknown".
"""
import json, re, sys
raw = json.load(open(sys.argv[1]))
ROAM = re.compile(r"stadtwerke|allego|ubitricity|qwello|eze|be emobil|totalenergies|total|shell|e\.on|eon|vattenfall|innogy|rwe|"
                  r"enbw|aral|lichtblick|e\.dis|edis|ewe|ionity|fastned|mer\b|wirelane|compleo|pfalzwerke|123energie|mennekes|"
                  r"circle k|eins|has.to.be|elli|ladenetz|energie und wasser potsdam|ewp|emb|sachsenenergie|e-wald|lidl|kaufland|"
                  r"aldi|edeka|rewe|ikea|mobility\+|plugsurfing|hubject|numbat|pfalz|juice|maingau|stromnetz", re.I)
BAD_CH = re.compile(r"tesla|supercharger", re.I)
charge, fuel = [], []
for lat, lon, name, op, kw, sockets in raw["charge"]:
    txt = f"{name} {op}"
    if BAD_CH.search(txt):
        continue
    if sockets and not re.search(r"type2|ccs|chademo|type1", sockets):
        continue  # schuko-only / bike chargers
    partner = "likely" if ROAM.search(txt) else "unknown"
    charge.append([lat, lon, (name or "")[:40], (op or "")[:40], int(kw) if kw else None, partner])
FUEL_LIKELY = re.compile(r"^(aral|total|totalenergies)$", re.I)
BAD_FUEL = re.compile(r"autogas|lpg|h2|wasserstoff|hydrogen|totalgaz|as 24|tyczka|gas gmbh", re.I)
for lat, lon, name, brand in raw["fuel"]:
    if BAD_FUEL.search(f"{name} {brand}"):
        continue
    partner = "likely" if FUEL_LIKELY.search((brand or "").strip()) or re.match(r"^(aral|total)", (name or ""), re.I) else "unknown"
    fuel.append([lat, lon, (name or "")[:40], (brand or "")[:40], partner])
out = {"meta": {"source": "OpenStreetMap contributors (ODbL), Berlin extract", "built": __import__("datetime").date.today().isoformat()},
       "charge_cols": ["lat", "lon", "name", "op", "kw", "partner"], "charge": charge,
       "fuel_cols": ["lat", "lon", "name", "op", "partner"], "fuel": fuel}
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, separators=(",", ":"))
from collections import Counter
print("charge", len(charge), Counter(c[5] for c in charge), "fuel", len(fuel), Counter(f[4] for f in fuel))
