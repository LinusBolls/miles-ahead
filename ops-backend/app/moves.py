"""Tonight's moves: one ranked list of cars the field team should move, grouped into runs one agent can do in one trip.

Two kinds of move, both derived from open engine alerts (so they share the alert lifecycle, outcomes and persistence):
  relocate  stranding alert (TabPFN / fallback p >= threshold), fresh ride end: drive the car to a nearby cell where
            expected ride starts in the next 3 h exceed the idle cars already there.
            value = expected idle hours avoided x EUR per car-hour (expected, model-based)
  clear     restricted_active (in an active no-parking window), restriction_soon (window opens within 2 h, deadline),
            far_from_legal inside the S-Bahn ring. value = exposure (fine + MILES admin fee + tow cost x observed tow rate)

Runs: greedy proximity clustering (seed = highest-priority open move, then nearest next pick-up within RUN_LINK_KM of the
previous drop-off), nearest-neighbour order, estimated minutes, EUR per run. Assigned runs freeze their membership.
Outcomes are tracked silently per move from later data (rented within 2 h / still idle; left in time / moved without ride)."""
import json, math, os, time
from collections import Counter, defaultdict
from datetime import timedelta

import numpy as np

from . import rules
from .engine import BER, iso
from .windows import pretty

RELOCATE_FRESH_H = float(os.environ.get("RELOCATE_FRESH_H", "2"))   # a ride end stays a Relocate candidate this long
RELOCATE_MIN_EUR = float(os.environ.get("RELOCATE_MIN_EUR", "8"))    # value floor: below this a trip is not worth it
RELOCATE_MAX_OPEN = int(os.environ.get("RELOCATE_MAX_OPEN", "30"))   # list stays short: highest-value relocations only
FAR_FRESH_H = float(os.environ.get("FAR_FRESH_H", "2"))
FAR_MAX_OPEN = int(os.environ.get("FAR_MAX_OPEN", "12"))
DEMAND_H = 3                     # demand horizon (hours) for Relocate targets
TARGET_MIN_KM, TARGET_MAX_KM, TARGET_EXT_KM = 1.0, 3.0, 4.0
RUN_LINK_KM, RUN_MAX = 1.6, 5
DRIVE_KMH, BIKE_KMH, HANDLE_MIN = 18.0, 13.0, 4.0
KM_LAT, KM_LON = 111.2, 67.8
SHORT = {"Charlottenburg-Wilmersdorf": "Charlottenburg", "Friedrichshain-Kreuzberg": "Kreuzberg", "Tempelhof-Schöneberg": "Schöneberg",
         "Steglitz-Zehlendorf": "Steglitz", "Treptow-Köpenick": "Treptow", "Marzahn-Hellersdorf": "Marzahn"}
AGENTS = [a.strip() for a in os.environ.get("FIELD_AGENTS", "Deniz,Mara,Jonas,Aylin,Tom").split(",") if a.strip()]
SKIP_REASONS = ["Car already gone", "No agent nearby", "Not worth the trip", "Data looks wrong"]
CELL = (0.0036, 0.0059)

# money (sources in rules.py / the "?" text)
ADMIN_FINE, ADMIN_TOW, TOW_FEE = 29.5, 70.0, 225.0
FINE_BY_AREA = {"no_stopping": 25, "loading_zone": 25, "taxi_stand": 25, "bus_lane": 55}
FINE_FAR = 25


def km(lat1, lon1, lat2, lon2):
    return math.hypot((lat2 - lat1) * KM_LAT, (lon2 - lon1) * KM_LON)


def strand_reason(inp, p):
    """Compact why for a Relocate row, from the drivers in our 2024 data: distance from the centre (5% strand within
    2 km, 56% beyond 15 km), ride-end hour (8% late morning, ~28% 19-21h), discounted at ride end (49% vs 18%), size (vans 45%)."""
    inp = inp or {}
    f = []
    k = inp.get("km_from_centre")
    if k is not None:
        f.append("city edge" if k > 15 else "outer ring" if k > 6 else None)
    h = inp.get("hour")
    if h is not None:
        f.append("night" if (h >= 22 or h < 5) else "evening" if h >= 18 else None)
    if inp.get("discounted"):
        f.append("discounted")
    f.append({"X": "van", "L": "large car"}.get(inp.get("size")))
    f = [x for x in f if x][:3]
    return " · ".join(f) if f else f"idle risk {p:.0%}"


def area_name(zone, street):
    if zone and any(ch.isdigit() for ch in zone[-3:]):
        head = zone.rpartition(" ")[0]
        return SHORT.get(head, head)
    return street or "Berlin"


class Demand:
    """Customer ride starts per cell x hour-of-week (June 3-16 2024, per week) + a legal parking point per cell."""

    def __init__(self, path, geo):
        z = np.load(path)
        self.key = z["key"]; self.dem = z["demand"].astype(np.float32)
        self.lat = z["lat"].astype(float); self.lon = z["lon"].astype(float); self.idle = z["idle"].astype(float)
        self.idx = {int(k): i for i, k in enumerate(self.key)}
        cls = geo.classify(self.lat, self.lon)
        self.street = [c.get("street") or "" for c in cls]
        self.city_idle_b = self.idle.mean(axis=0)
        self.zone = [c.get("paid_zone") or "" for c in cls]
        self.y = (self.lat - 52.5163) * KM_LAT; self.x = (self.lon - 13.3777) * KM_LON
        self.city_idle = float(np.mean(self.idle))

    def idle_at(self, i, tl):
        """Typical idle (h) after a ride end in cell i at this time of day (3-hour buckets, June 3-16 2024)."""
        b = tl.hour // 3
        return float(self.idle[i, b]) if i is not None else float(self.city_idle_b[b])

    @staticmethod
    def cell_key(lat, lon):
        return int(round(lat / CELL[0])) * 100000 + int(round(lon / CELL[1]))

    def expected(self, tl, hours=DEMAND_H):
        h = tl.weekday() * 24 + tl.hour
        frac = 1 - tl.minute / 60
        cols = [(h + k) % 168 for k in range(hours + 1)]
        w = np.array([frac] + [1.0] * (hours - 1) + [1 - frac], np.float32)
        return self.dem[:, cols] @ w

    def near(self, lat, lon, max_km):
        y, x = (lat - 52.5163) * KM_LAT, (lon - 13.3777) * KM_LON
        d = np.hypot(self.x - x, self.y - y)
        idx = np.where(d <= max_km)[0]
        return idx, d[idx]


class Moves:
    def __init__(self, engine, demand, scorer):
        self.e, self.D, self.sc = engine, demand, scorer
        self.sticky = {}         # move id -> target cell index
        self.cache = (0, None)

    def reset(self):
        self.sticky = {}
        self.cache = (0, None)

    # ---------- per-move construction ----------
    def _kind(self, a):
        k = a["kind"]
        if k == "stranding":
            return "relocate", "strand"
        if k == "restricted_active":
            return "clear", "active"
        if k == "restriction_soon":
            return "clear", "soon"
        if k == "far_from_legal" and a.get("area_type") == "no_legal_parking_nearby":
            return "clear", "far"
        return None, None

    def _candidates(self, t):
        """Open (or assigned, not yet final) move alerts."""
        out = []
        for a in self.e.alerts.values():
            kind, sub = self._kind(a)
            if not kind or a.get("city") not in ("BER", None):
                continue
            dec = a.get("decision") or {}
            if a["status"] == "resolved" and dec.get("action") != "assign":
                continue
            age_h = (t - a["_t"]).total_seconds() / 3600
            if dec.get("action") != "assign" and a["status"] != "resolved":
                if sub == "strand" and age_h > RELOCATE_FRESH_H:
                    continue
                if sub == "far" and age_h > FAR_FRESH_H:
                    continue
            if a["status"] == "resolved" and dec.get("action") == "assign":
                # assigned + finished: keep for today's assigned list only
                if (t - a.get("_out_t", a["_t"])).total_seconds() > 18 * 3600:
                    continue
            out.append((a, kind, sub))
        return out

    def _value_clear(self, a, sub):
        if sub == "far":   # no definite violation: only the observed tow rate is honest -> expected, fine not counted
            p_tow = rules.TOW_INNER_FAR
            return p_tow * (TOW_FEE + ADMIN_TOW), FINE_FAR, p_tow
        else:
            area = a.get("area_type") or "no_stopping"
            p_tow = rules.TOW_RESTRICTED.get(area, 0.0127)
            fine = FINE_BY_AREA.get(area, 25)
        return fine + ADMIN_FINE + p_tow * (TOW_FEE + ADMIN_TOW), fine, p_tow

    def _value_relocate(self, p, tgt, tl):
        V = self.sc.meta["value"]
        e_here = p * V["h_strand"] + (1 - p) * V["h_no_strand"]
        h_tgt = self.D.idle_at(tgt, tl)
        avoided = max(0.0, e_here - h_tgt)
        return avoided * V["eur_per_car_h"], e_here, h_tgt, avoided

    def build(self, t=None):
        """Snapshot: open runs, assigned runs, tally. Cached for 1 s."""
        now = time.time()
        if self.cache[1] is not None and now - self.cache[0] < 1.0:
            return self.cache[1]
        e = self.e
        t = t or e.engine_now()
        tl = t.astimezone(BER)
        D = self.D
        # supply: idle cars per cell now
        supply = np.zeros(len(D.key), np.float32)
        for pk in e.parked.values():
            i = D.idx.get(D.cell_key(pk.lat, pk.lon))
            if i is not None:
                supply[i] += 1
        exp = D.expected(tl)
        gap = exp - supply
        cands = self._candidates(t)
        # reserve sticky targets of assigned moves first, then of open ones
        cands.sort(key=lambda x: (0 if (x[0].get("decision") or {}).get("action") == "assign" else 1, -(x[0].get("probability") or 0)))
        moves = []
        for a, kind, sub in cands:
            m = self._move(a, kind, sub, t, tl, gap, exp, supply)
            if m:
                moves.append(m)
        live_ids = {m["id"] for m in moves}
        self.sticky = {k: v for k, v in self.sticky.items() if k in live_ids}
        open_m = [m for m in moves if m["status"] == "open"]
        hidden = 0
        for sub, cap in (("strand", RELOCATE_MAX_OPEN), ("far", FAR_MAX_OPEN)):
            grp = sorted([m for m in open_m if m["sub"] == sub and not m["test"]], key=lambda m: -m["value_eur"])
            drop = {m["id"] for m in grp[cap:]}
            hidden += len(drop)
            open_m = [m for m in open_m if m["id"] not in drop]
        assigned = [m for m in moves if m["status"] == "assigned"]
        runs = self._runs(open_m)
        arun = self._assigned_runs(assigned)
        snap = {"source": e.source, "now": iso(t), "now_local": tl.strftime("%a %d %b %H:%M"), "disp_now": e.disp(t),
                "summary": {"open_moves": len(open_m), "open_runs": len(runs),
                            "value_eur": round(sum(m["value_eur"] for m in open_m)),
                            "value_expected": round(sum(m["value_eur"] for m in open_m if m["value_kind"] == "expected")),
                            "value_exposure": round(sum(m["value_eur"] for m in open_m if m["value_kind"] == "exposure")),
                            "relocate": sum(1 for m in open_m if m["kind"] == "relocate"),
                            "clear": sum(1 for m in open_m if m["kind"] == "clear"),
                            "act_now": sum(1 for m in open_m if m["act_now"]), "hidden_low_value": hidden,
                            "relocate_min_eur": RELOCATE_MIN_EUR},
                "runs": runs, "assigned": arun, "tally": self.tally(t), "agents": AGENTS, "skip_reasons": SKIP_REASONS}
        self.cache = (now, snap)
        return snap

    def _target_relocate(self, a, gap):
        D = self.D
        mid = a["id"]
        prev = self.sticky.get(mid)
        assigned = (a.get("decision") or {}).get("action") == "assign"
        if prev is not None and (assigned or gap[prev] >= 0.5):
            gap[prev] -= 1
            return prev
        for max_km in (TARGET_MAX_KM, TARGET_EXT_KM):
            idx, d = D.near(a["lat"], a["lon"], max_km)
            ok = (d >= TARGET_MIN_KM) & (gap[idx] >= 1.0)
            own = (a.get("street") or "").strip()
            if own:
                ok &= np.array([D.street[i] != own for i in idx], dtype=bool)
            if ok.any():
                # prefer cells closer in (strand rate falls toward the centre) with spare demand, and short drives
                dc_car = math.hypot((a["lat"] - 52.5163) * KM_LAT, (a["lon"] - 13.3777) * KM_LON)
                dc_tgt = np.hypot(D.x[idx], D.y[idx])
                score = gap[idx] + 0.3 * (dc_car - dc_tgt) - 0.35 * d
                score[~ok] = -1e9
                j = int(np.argmax(score))
                tgt = int(idx[j])
                self.sticky[mid] = tgt
                gap[tgt] -= 1
                return tgt
        return None

    def _target_clear(self, a, gap):
        D = self.D
        prev = self.sticky.get(a["id"])
        if prev is not None:
            return prev
        idx, d = D.near(a["lat"], a["lon"], 1.2)
        idx, d = idx[d >= 0.05], d[d >= 0.05]
        if len(idx) == 0:
            return None
        score = np.where(gap[idx] >= 0.5, 1.0, 0.0) - 0.8 * d   # prefer a nearby legal spot where cars are needed
        tgt = int(idx[int(np.argmax(score))])
        self.sticky[a["id"]] = tgt
        gap[tgt] -= 1
        return tgt

    def _move(self, a, kind, sub, t, tl, gap, exp, supply):
        D = self.D
        dec = a.get("decision") or {}
        status = "assigned" if dec.get("action") == "assign" else ("skipped" if dec.get("action") == "skip" else "open")
        if status == "skipped":
            return None
        if kind == "relocate":
            tgt = self._target_relocate(a, gap)
            if tgt is None and status == "open":
                return None
            p = float(a.get("probability") or 0)
            value, e_here, h_tgt, avoided = self._value_relocate(p, tgt, tl)
            if value < RELOCATE_MIN_EUR and status == "open":
                self.sticky.pop(a["id"], None)
                return None
            reason = strand_reason(a.get("inputs"), p)
            vk = "expected"
            deadline = None
        else:
            tgt = self._target_clear(a, gap)
            value, fine, p_tow = self._value_clear(a, sub)
            vk = "expected" if sub == "far" else "exposure"
            deadline = a.get("deadline_local") if sub == "soon" else None
            lab = a.get("restriction_label") or rules.LABEL.get(a.get("area_type"), "restriction")
            hrs = (a.get("restriction_hours_pretty") or "").strip()
            act_txt = f"{lab}, {hrs}" if hrs and hrs.lower() not in ("always", "immer", "") else f"{lab}, at all times"
            reason = {"active": act_txt, "soon": f"{lab} starts {deadline}",
                      "far": f"{a.get('dist_to_legal_m') or 20:.0f} m from legal parking"}[sub]
        to = None
        if tgt is not None:
            to = {"lat": round(float(D.lat[tgt]), 6), "lon": round(float(D.lon[tgt]), 6), "street": D.street[tgt] or "nearby street",
                  "km": round(km(a["lat"], a["lon"], D.lat[tgt], D.lon[tgt]), 2)}
            if to["street"] == (a.get("street") or ""):   # nearest legal spot is further along the same street
                to["street"] = f"{max(50, int(round(to['km'] * 1000, -1)))} m along"
        out = None
        oc = self.outcome(a, kind, sub, t)
        m = {"id": a["id"], "kind": kind, "sub": sub, "plate": a["vehicle"].get("plate"), "vid": a["vehicle"].get("miles_id"),
             "car": a["vehicle"].get("model"), "from": {"lat": a["lat"], "lon": a["lon"], "street": a.get("street") or "", "zone": a.get("zone")},
             "to": to, "reason": reason, "value_eur": round(value, 1), "value_kind": vk, "deadline": deadline,
             "deadline_min": a.get("deadline_min") if sub == "soon" else None,
             "act_now": sub in ("active", "soon"), "created_at": a["created_at"],
             "age_min": round((t - a["_t"]).total_seconds() / 60), "status": status,
             "agent": dec.get("agent") or (dec.get("note") if status == "assigned" else None), "run_id": dec.get("run"),
             "scorer": a.get("model") if kind == "relocate" else None, "p": a.get("probability") if kind == "relocate" else None,
             "outcome": oc, "test": bool(a.get("test"))}
        if sub == "soon" and a.get("_deadline_t") is not None:
            m["deadline_min"] = max(0, round((a["_deadline_t"] - t).total_seconds() / 60))
        return m

    # ---------- outcomes ----------
    def outcome(self, a, kind, sub, t):
        """Silent outcome per move. Relocate: rented within 2 h of the move (assignment, else the ride end) vs still idle.
        Clear: left before the window / while at risk vs moved without a ride or still there."""
        if a.get("test"):
            return {"state": "pending", "text": "test event"}
        dec = a.get("decision") or {}
        t_ref = a.get("_dec_t") if dec.get("action") == "assign" and a.get("_dec_t") else a["_t"]
        o = a.get("outcome")
        via = (o or {}).get("via")
        if kind == "relocate":
            if o and via == "customer":
                m = (a.get("_out_t", t) - t_ref).total_seconds() / 60
                if m < 0:
                    return {"state": "neutral", "text": "rented before the move"}
                return {"state": "good" if m <= 120 else "bad", "text": f"rented after {m:.0f} min" if m <= 120 else f"rented after {m/60:.1f} h"}
            if o and via in ("ops", "tow"):
                return {"state": "neutral", "text": "moved without a ride"}
            if o and o.get("result") == "idle_12h_plus":
                return {"state": "bad", "text": "still idle at 12 h"}
            el = (t - t_ref).total_seconds() / 60
            if el > 120:
                return {"state": "bad", "text": "still idle 2 h later"}
            return {"state": "pending", "text": f"watching {el:.0f} min"}
        if o:
            if via in ("customer", "ops"):
                txt = {"soon": "left before the window opened", "active": "left the restriction", "far": "car left"}[sub]
                return {"state": "good", "text": txt}
            if via == "tow":
                return {"state": "bad", "text": "moved without a ride"}
            if o.get("result") == "still_parked":
                txt = {"soon": "still there when it started", "active": "stayed in the restriction", "far": "still parked 12 h"}[sub]
                return {"state": "bad", "text": txt}
            if o.get("result") == "test_expired":
                return {"state": "neutral", "text": "test cleared"}
        return {"state": "pending", "text": "watching"}

    # ---------- runs ----------
    def _priority(self, m):
        urgent = 1000 if m["sub"] == "active" else (600 - min(m["deadline_min"] or 120, 120) if m["sub"] == "soon" else 0)
        return urgent + m["value_eur"]

    def _run_obj(self, ms, rid):
        mins = 0.0
        route = []
        prev = None
        for m in ms:
            fr, to = m["from"], m["to"] or m["from"]
            if prev is not None:
                mins += km(prev["lat"], prev["lon"], fr["lat"], fr["lon"]) / BIKE_KMH * 60
            mins += km(fr["lat"], fr["lon"], to["lat"], to["lon"]) / DRIVE_KMH * 60 + HANDLE_MIN
            route.append([[fr["lon"], fr["lat"]], [to["lon"], to["lat"]]])
            prev = to
        names = Counter(area_name(m["from"].get("zone"), m["from"].get("street")) for m in ms)
        name = names.most_common(1)[0][0]
        dls = [m["deadline_min"] for m in ms if m["sub"] == "soon" and m["deadline_min"] is not None]
        return {"id": rid, "name": name, "n": len(ms), "minutes": int(math.ceil(mins / 5) * 5), "value_eur": round(sum(m["value_eur"] for m in ms)),
                "urgent": any(m["act_now"] for m in ms), "active": any(m["sub"] == "active" for m in ms),
                "deadline_min": min(dls) if dls else None, "deadline": min((m["deadline"] for m in ms if m["deadline"]), default=None),
                "moves": ms, "route": route}

    def _runs(self, open_m):
        """Runs never mix kinds: relocations (TabPFN) and clears (rules) are separate lists, so neither buries the other."""
        out = []
        for kind in ("relocate", "clear"):
            rs = self._runs_kind([m for m in open_m if m["kind"] == kind])
            for i, r in enumerate(rs):
                r["rank"] = i + 1
                r["kind"] = kind
            out += rs
        return out

    def _runs_kind(self, open_m):
        pool = sorted(open_m, key=lambda m: -self._priority(m))
        runs = []
        while pool:
            seed = pool.pop(0)
            run = [seed]
            cur = seed["to"] or seed["from"]
            while len(run) < RUN_MAX and pool:
                best, bd = None, RUN_LINK_KM
                for m in pool:
                    d = km(cur["lat"], cur["lon"], m["from"]["lat"], m["from"]["lon"])
                    if d < bd:
                        best, bd = m, d
                if best is None:
                    break
                run.append(best); pool.remove(best)
                cur = best["to"] or best["from"]
            runs.append(self._run_obj(run, f"run:{seed['id']}"))
        runs.sort(key=lambda r: (0 if r["active"] else 1 if r["deadline_min"] is not None else 2,
                                 r["deadline_min"] if r["deadline_min"] is not None else 0, -r["value_eur"]))
        return runs

    def _assigned_runs(self, assigned):
        by = defaultdict(list)
        for m in assigned:
            by[m["run_id"] or m["id"]].append(m)
        out = []
        for rid, ms in by.items():
            ms.sort(key=lambda m: m.get("seq") or 0)
            r = self._run_obj(ms, rid)
            r["kind"] = ms[0]["kind"]
            r["agent"] = ms[0]["agent"]
            r["done"] = sum(1 for m in ms if m["outcome"]["state"] != "pending")
            r["good"] = sum(1 for m in ms if m["outcome"]["state"] == "good")
            out.append(r)
        out.sort(key=lambda r: r["moves"][0]["created_at"], reverse=True)
        return out

    # ---------- tally ----------
    def tally(self, t):
        tl = t.astimezone(BER)
        day = tl.date()
        n = Counter()
        for a in self.e.alerts.values():
            dec = a.get("decision") or {}
            if a.get("test") or not dec.get("action") or a.get("_dec_t") is None:
                continue
            if a["_dec_t"].astimezone(BER).date() != day:
                continue
            kind, sub = self._kind(a)
            if not kind:
                continue
            if dec["action"] == "skip":
                n["skipped"] += 1
                continue
            n["assigned"] += 1
            st = self.outcome(a, kind, sub, t)["state"]
            if kind == "relocate":
                n["rel_good" if st == "good" else "rel_bad" if st == "bad" else "rel_pending" if st == "pending" else "rel_other"] += 1
            else:
                n["clr_good" if st == "good" else "clr_bad" if st == "bad" else "clr_pending" if st == "pending" else "clr_other"] += 1
        return dict(n)

    # ---------- detail ----------
    def detail(self, mid):
        e = self.e
        a = e.alerts.get(mid)
        if not a:
            return None
        snap = self.build()
        m = next((m for r in snap["runs"] + snap["assigned"] for m in r["moves"] if m["id"] == mid), None)
        kind, sub = self._kind(a)
        t = e.engine_now(); tl = t.astimezone(BER)
        d = {"move": m, "kind": kind, "sub": sub, "vehicle": a["vehicle"], "created_at": a["created_at"], "test": bool(a.get("test"))}
        V = self.sc.meta["value"]
        if kind == "relocate":
            p = float(a.get("probability") or 0)
            model = a.get("model") or "fallback"
            cal = self.sc.calibration("TabPFN" if model == "TabPFN" else "fallback", p)
            met = self.sc.meta["metrics"]["tabpfn_clean_split"]
            d["model"] = {"name": model, "p": p, "threshold": self.sc.threshold("TabPFN" if model == "TabPFN" else "fallback"),
                          "calibration": cal, "basis": self.sc.meta["calibration"]["tabpfn_basis" if model == "TabPFN" else "gbm_basis"],
                          "auc": met["auc"] if model == "TabPFN" else rules.VALIDATION.get("auc"), "inputs": a.get("inputs")}
            tgt = self.sticky.get(mid)
            D = self.D
            if tgt is not None:
                sup = sum(1 for pk in e.parked.values() if D.cell_key(pk.lat, pk.lon) == int(D.key[tgt]))
                d["target"] = {"street": D.street[tgt], "zone": D.zone[tgt], "expected_starts_3h": round(float(D.expected(tl)[tgt]), 1),
                               "idle_now": sup, "typical_idle_h": round(D.idle_at(tgt, tl), 1), "km": m["to"]["km"] if m and m["to"] else None}
            value, e_here, h_tgt, avoided = self._value_relocate(p, tgt, tl)
            d["value"] = {"eur": round(value, 1), "kind": "expected", "e_idle_here_h": round(e_here, 1), "idle_target_h": round(h_tgt, 1),
                          "avoided_h": round(avoided, 1), "eur_per_car_h": V["eur_per_car_h"], "h_strand": V["h_strand"], "h_no_strand": V["h_no_strand"]}
        else:
            value, fine, p_tow = self._value_clear(a, sub)
            d["restriction"] = {"label": a.get("restriction_label") or rules.LABEL.get(a.get("area_type")), "hours": a.get("restriction_hours_pretty"),
                                "reason": a.get("restriction_reason"), "street": a.get("street"), "deadline": a.get("deadline_local"),
                                "dist_to_legal_m": a.get("dist_to_legal_m")}
            d["value"] = {"eur": round(value, 1), "kind": "expected" if sub == "far" else "exposure", "fine": fine, "admin_fine": ADMIN_FINE, "tow_fee": TOW_FEE, "admin_tow": ADMIN_TOW,
                          "p_tow": p_tow, "p_tow_basis": "moved without a customer ride, MILES Berlin June 2024" + (" (3.2% vs 1.4% for legal parks)" if sub == "far" else "")}
        return d
