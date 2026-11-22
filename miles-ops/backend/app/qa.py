"""QA test events (POST /qa/inject): one fake alert of a given kind, pushed through the same engine path as real alerts
(_new_alert -> SSE `alert`, plus a `park` map event for the parking kinds). Fake events carry "test": true; they are
never persisted to the decision store, are excluded from the scorecard and never touch the parked-car registry, so the
fee ledger and counters stay clean. They expire after 10 min (counters loop) and vanish on any replay restart/reset.

Locations are real Berlin ride-end positions from the replay data, classified with the same geodata as live, so the
street, paid zone and restriction type are plausible. Plates are masked like everywhere else (B-MI ••NN)."""
import random, threading, time

import numpy as np

from . import rules
from .engine import BER, KABBR, Park
from .geo import RESTRICTED_AREAS
from .windows import active, parse

KINDS = ("restricted_active", "far_from_legal", "stranding", "restriction_soon", "low_fuel", "ops", "damage")
MODELS = [("VW ID.3", "S", True), ("VW Polo", "S", False), ("Tesla Model Y", "M", True), ("Audi A4 Avant", "M", False),
          ("VW T6", "L", False), ("Seat Leon", "S", False), ("BMW iX1", "M", True)]
# restriction windows to fall back on when the sampled spot's own window is not active at engine time ("" = always)
WINDOWS = ["Mo-Fr 07:00-19:00", "Mo-Sa 07:00-20:00", "Mo-So 06:00-22:00", ""]
OPS_STATUSES = ["IN_OPS", "RELOCATION", "REPAIR"]


class QA:
    def __init__(self, geo, model, lat, lon, capacity=12, refill_s=3.0):
        self.geo, self.model = geo, model
        self.lat, self.lon = lat, lon
        self.pool = None
        self.lock = threading.Lock()
        self.n = 0
        self.rng = random.Random()
        self.capacity, self.refill_s = capacity, refill_s
        self.tokens, self.t_tok = float(capacity), time.time()

    # ---- rate limit: token bucket shared by all callers (it is a demo box, not a public API) ----
    def allow(self):
        now = time.time()
        self.tokens = min(self.capacity, self.tokens + (now - self.t_tok) / self.refill_s)
        self.t_tok = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True, 0
        return False, round((1 - self.tokens) * self.refill_s, 1)

    # ---- location pool (lazy: classifying 20k points takes ~1-2 s, so call it from a worker thread) ----
    def ensure_pool(self):
        with self.lock:
            if self.pool is not None:
                return self.pool
            rs = np.random.default_rng(7)
            idx = rs.choice(len(self.lat), size=min(20000, len(self.lat)), replace=False)
            la, lo = self.lat[idx], self.lon[idx]
            cls = self.geo.classify(la, lo)
            pool = {"restricted": [], "far": [], "legal": []}
            for y, x, c in zip(la, lo, cls):
                if not c.get("street"):
                    continue
                a = c["area_type"]
                if a in RESTRICTED_AREAS:
                    pool["restricted"].append((float(y), float(x), c))
                elif a in ("no_legal_parking_nearby", "no_legal_parking_nearby_outer") and not c["offstreet"] \
                        and c.get("dist_to_legal_m") is not None and 20 < c["dist_to_legal_m"] <= 300:
                    pool["far"].append((float(y), float(x), c))
                elif a == "legal" and c.get("paid_zone") and len(pool["legal"]) < 3000:
                    pool["legal"].append((float(y), float(x), c))
            self.pool = pool
            return pool

    def inject(self, e, kind):
        pool = self.ensure_pool()
        r = self.rng
        t = e.engine_now()
        tl = t.astimezone(BER)
        self.n += 1
        vid = -(500000 + self.n)
        model, size, electric = r.choice(MODELS)
        charge = r.randint(4, 9) if kind == "low_fuel" else r.randint(22, 88)
        v = e.vehicle(vid)
        v.update(plate=f"B-MI ••{r.randint(10, 99)}", model=model, size_class=size, electric=electric, charge=charge, city="BER", damage=0)
        bucket = {"restricted_active": "restricted", "restriction_soon": "restricted", "far_from_legal": "far"}.get(kind, "legal")
        extra = {"test": True}
        lat, lon, cls = r.choice(pool[bucket] or pool["legal"])
        cls = dict(cls)
        lat += r.uniform(-0.00008, 0.00008); lon += r.uniform(-0.00012, 0.00012)  # a few metres: no two fakes on one pixel
        if kind == "restricted_active":
            if cls["area_type"] not in RESTRICTED_AREAS:
                cls.update(area_type="no_stopping", restriction_type="Haltverbot", restriction_reason="")
            w = parse(cls.get("restriction_hours") or "")
            if w in (None, "unparsed") or not active(w, tl):
                cls["restriction_hours"] = next(h for h in WINDOWS if h == "" or active(parse(h), tl))
            spec = rules.restricted_active(cls, 0.0, False)
        elif kind == "restriction_soon":
            from datetime import timedelta
            if cls["area_type"] not in RESTRICTED_AREAS:
                cls.update(area_type="no_stopping", restriction_type="Haltverbot", restriction_reason="")
            mins = r.choice([25, 40, 55, 70, 95])
            dl = tl + timedelta(minutes=mins)
            dl = dl.replace(minute=(dl.minute // 5) * 5, second=0, microsecond=0)
            cls["restriction_hours"] = f"Mo-So {dl:%H:%M}-{min(23, dl.hour + 6):02d}:00"
            spec = rules.restriction_soon(cls, mins, dl.strftime("%H:%M"))
            extra.update(deadline_local=dl.strftime("%H:%M"), deadline_min=mins, _deadline_t=t + timedelta(minutes=mins))
        elif kind == "far_from_legal":
            if cls["area_type"] != "no_legal_parking_nearby":   # moves only clear far parks inside the S-Bahn ring
                cls.update(area_type="no_legal_parking_nearby", inside_sbahn_ring=True)
            spec = rules.far_from_legal(cls)
        elif kind == "stranding":
            thr = e.scorer.threshold("TabPFN") if e.scorer else 0.46
            p = round(r.uniform(thr + 0.03, 0.85), 3)
            spec = rules.stranding(cls, p, thr, None)
            extra.update(model="test", inputs={"hour": tl.hour, "weekday": tl.strftime("%a"), "charge": charge, "size": size, "car": model,
                                              "electric": electric, "damage_count": 0, "km_from_centre": None})
        elif kind == "low_fuel":
            spec = rules.fleet_low_fuel("BER", v["plate"], float(charge), electric)
        elif kind == "ops":
            spec = rules.fleet_ops("BER", v["plate"], r.choice(OPS_STATUSES))
        else:
            spec = rules.fleet_damage("BER", v["plate"], r.randint(1, 3))
        aid = f"{e.prefix}qa{self.n}_{KABBR[kind]}"
        a = e._new_alert(aid, t, vid, lat, lon, cls, spec, extra=extra)
        if a is not None and kind in ("restricted_active", "far_from_legal", "stranding", "restriction_soon"):
            e.publish_park(vid, t, Park(aid, vid, t, lat, lon, cls, "ride"), "ride", [kind], test=True)
        return a
