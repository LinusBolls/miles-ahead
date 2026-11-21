"""miles-drive: which MILES cars in Berlin pay you credit right now.

Reads the live scraper's Postgres through the read-only role ops_ro (one connection), refreshes a snapshot every
REFRESH_S seconds in a background thread and serves it pre-serialised with an ETag, so 100 polling phones cost
nothing. It never talks to MILES.
"""
import gzip, hashlib, json, logging, math, os, sqlite3, threading, time
from collections import deque
from datetime import datetime, timezone

import psycopg
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

log = logging.getLogger("drive")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

DSN = os.environ.get("OPS_DB_DSN", "")
REFRESH_S = float(os.environ.get("REFRESH_S", "10"))
DATA_DIR = os.environ.get("DATA_DIR", "/data")
STATIONS = os.environ.get("STATIONS", os.path.join(os.path.dirname(__file__), "stations.json"))
UTC = timezone.utc

# ---- money (see README for sources; all EUR) ----
CREDIT_EV = 10.0        # plugged into a partner charger at rental end, battery <=30% then, >1 km driven, km rate (HC 5980672773650)
CREDIT_FUEL = 5.0       # tank <25% at rental start, filled to 100% at a partner station, km rate; refuelling is started in
                        # the app ("Refueling" -> pump number -> "Unlock nozzle"), no payment (HC 360015528380, 360015531299)
EV_MAX = 30             # credit threshold
EV_SHOW = 35            # also show EVs a few km above the threshold
FUEL_MAX = 25           # strictly below
ROAD_FACTOR = 1.35      # straight line -> street distance in Berlin
# Assumed standard km rates. miles-mobility.com/de/pricing (Nov 2026) only gives "ab" prices: S/M from 0.79/km + 1
# unlock, Premium from 1.09/km + 2, L/XL from 1.29/km + 2. 0.79 is the discounted Green Rate, so for S/M we assume a
# conservative 0.98/km; the real price is shown in the app before booking.
KM_PRICE = {"S": 0.98, "M": 0.98, "P": 1.29, "L": 1.29, "X": 1.29}
UNLOCK = {"S": 1.0, "M": 1.0, "P": 2.0, "L": 2.0, "X": 2.0}
ANNIV_KM = 0.59         # 10_ANNIVERSARY cars: 0.59/km (help center article 38958991630866)
DYNAMIC_FACTOR = 0.8    # DYNAMIC / Green Rate: "save up to 20%"

SQL_CARS = '''SELECT l."milesId", l.latitude, l.longitude, l.charge, l.range, l.charging, l.discounted, l."discountSource",
                     v."licensePlate", v.color, m.name, m.electric, s.name
              FROM "MilesVehicleLastKnown" l JOIN "MilesVehicle" v USING ("milesId")
              JOIN "MilesVehicleModel" m ON m.id = v."modelId" LEFT JOIN "MilesVehicleSize" s ON s.id = m."sizeId"
              JOIN "MilesCity" c ON c.id = v."firstFoundCityId"
              WHERE l.status = 'DEPLOYED_FOR_RENTAL' AND c."milesId" = 'BER' '''
SQL_FRESH = 'SELECT max(at) FROM vehicle_changes'
# Rides that ended today (Berlin) where a customer evidently refuelled (<25% -> >=95%) or plugged in an EV.
SQL_DONE = '''WITH r AS (
  SELECT vc.*, lag(new_charge) OVER w AS prev_charge FROM vehicle_changes vc
  WHERE vc.at >= date_trunc('day', now() AT TIME ZONE 'Europe/Berlin') AT TIME ZONE 'Europe/Berlin' - interval '6 hours'
  WINDOW w AS (PARTITION BY "milesId" ORDER BY id))
SELECT r.at, m.electric, coalesce(r.old_charge, r.prev_charge), r.new_charge, r.new_charging
FROM r JOIN "MilesVehicle" v USING ("milesId") JOIN "MilesVehicleModel" m ON m.id = v."modelId"
JOIN "MilesCity" c ON c.id = v."firstFoundCityId"
WHERE c."milesId" = 'BER' AND r.new_status = 'DEPLOYED_FOR_RENTAL'
  AND r.old_status IN ('USER_IN_RIDE', 'BOOKED_BY_USER', 'PAUSED_BY_USER')
  AND r.at >= date_trunc('day', now() AT TIME ZONE 'Europe/Berlin') AT TIME ZONE 'Europe/Berlin'
  AND ((NOT m.electric AND r.new_charge >= 95 AND coalesce(r.old_charge, r.prev_charge) < 25)
    OR (m.electric AND r.new_charging AND r.new_charge <= 30))
ORDER BY r.at'''


def hav_m(la1, lo1, la2, lo2):
    p = math.pi / 180
    a = math.sin((la2 - la1) * p / 2) ** 2 + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2
    return 12742000 * math.asin(math.sqrt(a))


def mask_plate(pl):
    """'B-XX 1234' -> '••34' (last two characters only)."""
    pl = (pl or "").replace(" ", "")
    return "••" + pl[-2:] if len(pl) >= 2 else "••"


class Grid:
    """Tiny lat/lon bucket index for nearest-station lookups."""
    def __init__(self, items, cell=0.01):
        self.cell, self.b = cell, {}
        for it in items:
            self.b.setdefault((int(it["lat"] / cell), int(it["lon"] / cell)), []).append(it)

    def nearest(self, lat, lon, pred=None, k=1, max_ring=12):
        ci, cj = int(lat / self.cell), int(lon / self.cell)
        found = []
        for ring in range(max_ring + 1):
            for i in range(ci - ring, ci + ring + 1):
                for j in range(cj - ring, cj + ring + 1):
                    if max(abs(i - ci), abs(j - cj)) != ring:
                        continue
                    for it in self.b.get((i, j), ()):
                        if pred is None or pred(it):
                            found.append((hav_m(lat, lon, it["lat"], it["lon"]), it))
            # a ring-r cell is at least (r-1)*cell away; stop once we have k results closer than that
            if len(found) >= k and sorted(found, key=lambda x: x[0])[k - 1][0] < (ring) * self.cell * 111000 * 0.6:
                break
        found.sort(key=lambda x: x[0])
        return found[:k]


def load_stations():
    d = json.load(open(STATIONS))
    ch = [dict(zip(d["charge_cols"], r)) for r in d["charge"]]
    fu = [dict(zip(d["fuel_cols"], r)) for r in d["fuel"]]
    log.info("stations: %d charging, %d fuel", len(ch), len(fu))
    return Grid(ch), Grid(fu), d.get("meta", {})


class Store:
    """'I did it' taps, SQLite, one row per tap (car id + day + kind), deduped per client token."""
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS did (at TEXT, day TEXT, car INTEGER, kind TEXT, token TEXT, UNIQUE(day, car, token))")
        self.lock = threading.Lock()

    def add(self, car, kind, token):
        now = datetime.now(UTC)
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO did VALUES (?,?,?,?,?)", (now.isoformat(), now.date().isoformat(), car, kind, token))
            self.db.commit()
        return self.count()

    def count(self):
        with self.lock:
            return self.db.execute("SELECT count(*) FROM did").fetchone()[0]


class Snapshot:
    def __init__(self):
        self.conn = None
        self.body = b'{"ok":false,"status":"starting"}'
        self.gz = gzip.compress(self.body)
        self.etag = '"0"'
        self.ok = False
        self.error = None
        self.refreshed = None
        self.prev = {}            # car id -> item (qualifying set of the previous refresh)
        self.first_seen = {}      # car id -> epoch s when it started qualifying
        self.events = deque(maxlen=40)
        self.done = {"refuels": 0, "charges": 0, "credits_eur": 0.0, "since": None}
        self.done_at = 0
        self.charge_grid, self.fuel_grid, self.st_meta = load_stations()
        self.near_cache = {}      # (id, lat, lon) -> station info

    def _q(self, sql):
        try:
            if self.conn is None or self.conn.closed:
                self.conn = psycopg.connect(DSN, autocommit=True, connect_timeout=5, application_name="miles-drive")
            with self.conn.cursor() as cur:
                cur.execute(sql)
                return cur.fetchall()
        except psycopg.Error:
            try:
                self.conn and self.conn.close()
            except Exception:
                pass
            self.conn = None
            raise

    def _station(self, kind, vid, lat, lon):
        key = (kind, vid, round(lat, 5), round(lon, 5))
        if key in self.near_cache:
            return self.near_cache[key]
        grid = self.charge_grid if kind == "ev" else self.fuel_grid
        cand = grid.nearest(lat, lon, k=8)
        # prefer a likely partner station if it costs at most 600 m more than the nearest one
        best = cand[0] if cand else None
        partner = [c for c in cand if c[1].get("partner") == "likely"]
        if partner and best and partner[0][0] - best[0] <= (600 if kind == "ev" else 1500):
            best = partner[0]
        out = None
        if best:
            m, s = best
            out = {"lat": s["lat"], "lon": s["lon"], "name": s.get("name") or "", "op": s.get("op") or "",
                   "kw": s.get("kw"), "partner": s.get("partner"), "m": round(m)}
        self.near_cache[key] = out
        return out

    def refresh(self):
        t0 = time.time()
        rows = self._q(SQL_CARS)
        fresh = self._q(SQL_FRESH)[0][0]
        now = time.time()
        items, total_ev, total = {}, 0, len(rows)
        for vid, lat, lon, charge, rng, charging, disc, dsrc, plate, color, model, electric, size in rows:
            total_ev += bool(electric)
            kinds = []
            if electric and not charging and charge <= EV_SHOW:
                kinds.append("ev")
            if not electric and charge < FUEL_MAX:
                kinds.append("fuel")
            bonus = None
            if dsrc and dsrc.startswith("BONUSRIDE-"):
                try:
                    bonus = int(dsrc.split("-", 1)[1])   # inferred: fixed EUR amount off the ride (blue icon in app)
                except ValueError:
                    bonus = None
            if disc or (bonus and bonus >= 2):   # 1 EUR bonus rides are everywhere and not worth a walk
                kinds.append("deal")
            if not kinds:
                continue
            sz = size if size in KM_PRICE else "S"
            km_price = KM_PRICE[sz]
            if dsrc == "10_ANNIVERSARY":
                km_price = ANNIV_KM
            elif disc:
                km_price = round(km_price * DYNAMIC_FACTOR, 2)
            it = {"id": vid, "lat": round(lat, 6), "lon": round(lon, 6), "pct": charge, "range": rng, "model": model,
                  "size": sz, "color": color, "plate": mask_plate(plate), "ev": bool(electric), "kinds": kinds,
                  "km_price": km_price, "unlock": UNLOCK[sz], "deal": dsrc if (disc or bonus) else None, "bonus": bonus}
            if "ev" in kinds:
                it["st"] = self._station("ev", vid, lat, lon)
                # km to drive before the battery is at 30%: from the car's own range-per-percent
                it["km_to_threshold"] = 0 if charge <= EV_MAX else round((charge - EV_MAX) * (rng / max(charge, 1)), 1)
            elif "fuel" in kinds:
                it["st"] = self._station("fuel", vid, lat, lon)
            items[vid] = it
        # appear / disappear events (only for credit cars, deals are noise)
        cur_ids = set(items)
        first_run = not self.prev
        for vid in cur_ids - set(self.prev):
            self.first_seen[vid] = 0 if first_run else now   # 0 = already there when the service started
            if self.prev and set(items[vid]["kinds"]) - {"deal"}:
                self.events.appendleft({"t": int(now), "type": "new", "id": vid, "model": items[vid]["model"],
                                        "pct": items[vid]["pct"], "ev": items[vid]["ev"]})
        for vid in set(self.prev) - cur_ids:
            self.first_seen.pop(vid, None)
            p = self.prev[vid]
            if set(p["kinds"]) - {"deal"}:
                self.events.appendleft({"t": int(now), "type": "gone", "id": vid, "model": p["model"], "pct": p["pct"], "ev": p["ev"]})
        for vid, it in items.items():
            it["since"] = int(self.first_seen.get(vid, now))
        self.prev = items
        if len(self.near_cache) > 20000:
            self.near_cache.clear()
        if now - self.done_at > 60:
            try:
                d = self._q(SQL_DONE)
                ref = sum(1 for r in d if not r[1]); chg = sum(1 for r in d if r[1])
                self.done = {"refuels": ref, "charges": chg, "credits_eur": ref * CREDIT_FUEL + chg * CREDIT_EV,
                             "last": d[-1][0].isoformat() if d else None}
                self.done_at = now
            except Exception:
                log.exception("done query failed")
        out = {
            "ok": True, "city": "BER",
            "generated_at": datetime.fromtimestamp(now, UTC).isoformat(),
            "data_at": fresh.isoformat() if fresh else None,
            "fleet": {"deployed": total, "electric": total_ev},
            "rules": {"credit_ev": CREDIT_EV, "credit_fuel": CREDIT_FUEL, "ev_max": EV_MAX, "fuel_max": FUEL_MAX,
                      "road_factor": ROAD_FACTOR, "km_price": KM_PRICE, "unlock": UNLOCK},
            "done_today": self.done,
            "did_count": store.count(),
            "events": list(self.events)[:15],
            "cars": sorted(items.values(), key=lambda x: x["id"]),
        }
        body = json.dumps(out, separators=(",", ":"), ensure_ascii=False).encode()
        self.body, self.gz = body, gzip.compress(body, 6)
        self.etag = '"' + hashlib.md5(body).hexdigest()[:16] + '"'
        self.ok, self.error, self.refreshed = True, None, now
        log.debug("refresh %d rows -> %d items in %.0f ms", total, len(items), (time.time() - t0) * 1000)

    def loop(self):
        while True:
            try:
                self.refresh()
            except Exception as ex:
                self.ok, self.error = False, f"{type(ex).__name__}: {str(ex)[:200]}"
                log.exception("refresh failed")
            time.sleep(REFRESH_S)


S = Snapshot()
store = Store(os.path.join(DATA_DIR, "drive.sqlite"))
app = FastAPI(title="miles-drive", docs_url=None, redoc_url=None, openapi_url=None)


@app.on_event("startup")
def _start():
    threading.Thread(target=S.loop, daemon=True, name="refresh").start()


@app.get("/health")
def health():
    age = time.time() - S.refreshed if S.refreshed else None
    return {"ok": S.ok and age is not None and age < 60, "error": S.error, "snapshot_age_s": round(age, 1) if age else None,
            "cars": len(S.prev)}


@app.get("/cars")
def cars(request: Request):
    hdr = {"ETag": S.etag, "Cache-Control": "no-cache", "Vary": "Accept-Encoding"}
    if request.headers.get("if-none-match") == S.etag:
        return Response(status_code=304, headers=hdr)
    if "gzip" in request.headers.get("accept-encoding", ""):
        return Response(S.gz, media_type="application/json", headers={**hdr, "Content-Encoding": "gzip"})
    return Response(S.body, media_type="application/json", headers=hdr)


_rate = {}


@app.post("/did")
async def did(request: Request):
    """'I did it' tap. Honour system, deduped per (day, car, client token); light per-IP rate limit."""
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "")
    now = time.time()
    hits = [t for t in _rate.get(ip, []) if now - t < 60]
    if len(hits) >= 10:
        return JSONResponse({"ok": False, "error": "slow down"}, status_code=429)
    _rate[ip] = hits + [now]
    if len(_rate) > 5000:
        _rate.clear()
    try:
        b = await request.json()
        car, kind, token = int(b.get("car")), str(b.get("kind", ""))[:8], str(b.get("token", ""))[:40]
    except Exception:
        return JSONResponse({"ok": False, "error": "bad request"}, status_code=400)
    if kind not in ("ev", "fuel") or not token:
        return JSONResponse({"ok": False, "error": "bad request"}, status_code=400)
    return {"ok": True, "count": store.add(car, kind, token)}


@app.get("/did")
def did_count():
    return {"count": store.count()}
