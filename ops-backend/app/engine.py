"""State engine shared by the live and replay sources: parked-car registry, alerts, outcomes, ledger, counters, SSE fan-out.
All engine methods take engine time `t` (tz-aware UTC). For replay that is June-2024 data time; `disp(t)` maps it to wall clock."""
import asyncio, json, math, time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import rules
from .windows import parse, active, minutes_until_active, pretty

BER = ZoneInfo("Europe/Berlin")
UTC = timezone.utc
RIDE_STATUSES = {"USER_IN_RIDE", "PAUSED_BY_USER"}
KABBR = {"restricted_active": "ra", "far_from_legal": "ff", "stranding": "st", "ops": "op", "low_fuel": "lf", "damage": "dm",
         "restriction_soon": "rs"}
PARK_KINDS = ("restricted_active", "far_from_legal", "stranding", "restriction_soon")
SOON_MIN = 120  # restriction windows opening within this many minutes become "move before HH:MM" moves
INTERVENTIONS = {"dispatch", "notify_customer", "relocate", "discount", "refuel", "inspect"}


def iso(t):
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def hav_m(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


class Park:
    __slots__ = ("pid", "vid", "t0", "lat", "lon", "cls", "rwin", "zwin", "fee", "zone", "kind", "booked_at")

    def __init__(self, pid, vid, t0, lat, lon, cls, kind):
        self.pid, self.vid, self.t0, self.lat, self.lon, self.cls, self.kind = pid, vid, t0, lat, lon, cls, kind
        self.rwin = parse(cls["restriction_hours"]) if cls["area_type"] in ("no_stopping", "loading_zone", "bus_lane", "taxi_stand") else False
        self.zone = cls.get("paid_zone") or None
        self.fee = cls.get("paid_zone_fee_eur_h") or 0.0
        self.zwin = parse(cls.get("paid_zone_hours") or "") if self.zone else False
        if self.zone and self.zwin is None:
            self.zwin = False  # paid zone without hours string: don't bill (same as fee_ledger.py)
        self.booked_at = None

    def restricted_now(self, tl):
        return self.rwin is not False and active(self.rwin, tl)

    def far(self):
        a = self.cls["area_type"]
        d = self.cls.get("dist_to_legal_m")
        return a in ("no_legal_parking_nearby", "no_legal_parking_nearby_outer") and not self.cls["offstreet"] and d is not None and d <= 300

    def billing_now(self, tl):
        return bool(self.zone) and self.zwin not in (False, "unparsed") and active(self.zwin, tl)


class Engine:
    fleet_ttl_h = 6.0   # open fleet alerts (ops/low_fuel/damage) expire after this many engine hours

    def __init__(self, source, geo, model, store, id_prefix):
        self.source, self.geo, self.model, self.store, self.prefix = source, geo, model, store, id_prefix
        self.scorer = None          # StrandScorer (thresholds per model); set by main
        self.strand_queue = None    # live only: ride ends waiting for the TabPFN micro-batch
        self.moves = None
        self.reset()
        self.subs = set()

    def reset(self):
        self.alerts = {}                       # id -> alert
        self.seen = set()                      # every alert id ever emitted (alerts may be pruned)
        self.open = defaultdict(dict)          # vid -> {kind: alert id}
        self.parked = {}                       # vid -> Park (Berlin only)
        self.vehicles = {}                     # vid -> vehicle dict
        self.ride_ends = defaultdict(int)      # local date -> count (Berlin customer ride ends)
        self.ledger = defaultdict(lambda: defaultdict(float))  # local date -> zone -> eur
        self.zone_info = {}                    # zone -> (fee, hours)
        self.decisions = {}                    # alert id -> decision (latest)
        self.last_data_t = None
        self.now_t = None
        self._ctr_cache = (0, None)
        self.stats = defaultdict(int)          # emitted alerts per kind
        self.p_hist = deque(maxlen=2000)       # recent stranding scores (telemetry)
        self.t_start = None
        self.quiet = False                     # pre-warm: build state without SSE; alerts get prewarm=true
        self.last_event_real = None            # wall-clock time of the last published alert/park/depart (UI "last event")

    # ---- time helpers (overridden for replay) ----
    def disp(self, t):
        return iso(t)

    def engine_now(self):
        return datetime.now(UTC)

    # ---- SSE ----
    def publish(self, event, data, city=None):
        if self.quiet:
            return
        if event in ("alert", "park", "depart"):
            self.last_event_real = time.time()
        if not self.subs:
            return
        msg = (event, data, city)
        for q in list(self.subs):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                # slow client (background tab, sleeping laptop): drop its stale backlog and tell it to reload /state,
                # instead of replaying minutes-old events in front of new ones
                while not q.empty():
                    q.get_nowait()
                q.put_nowait(("reset", {"reason": "backlog_dropped"}, None))

    # ---- vehicles ----
    def vehicle(self, vid):
        v = self.vehicles.get(vid)
        if v is None:
            v = {"miles_id": vid, "plate": "••", "model": None, "size_class": None, "charge": None, "city": None, "electric": False}
            self.vehicles[vid] = v
        return v

    def vpub(self, vid):
        v = self.vehicle(vid)
        return {k: v.get(k) for k in ("miles_id", "plate", "model", "size_class", "charge", "city")}

    # ---- alerts ----
    def _new_alert(self, aid, t, vid, lat, lon, cls, spec, extra=None):
        if aid in self.alerts or aid in self.seen:
            return None
        self.seen.add(aid)
        v = self.vpub(vid)
        a = {"id": aid, "kind": spec["kind"], "severity": spec["severity"], "created_at": self.disp(t), "status": "open",
             "vehicle": v, "lat": round(lat, 6) if lat is not None else None, "lon": round(lon, 6) if lon is not None else None,
             "zone": (cls or {}).get("paid_zone") or None, "title": spec["title"], "evidence": spec["evidence"],
             "recommendation": spec["recommendation"], "probability": spec.get("probability"), "decision": None, "outcome": None,
             # additive fields
             "city": v.get("city"), "street": (cls or {}).get("street") or None, "area_type": (cls or {}).get("area_type"),
             "source": self.source, "_t": t, "_real": time.time()}
        if cls:
            a["dist_to_legal_m"] = cls.get("dist_to_legal_m")
            if cls.get("area_type") in ("no_stopping", "loading_zone", "bus_lane", "taxi_stand"):
                a["restriction_label"] = rules.restriction_label(cls)
                a["restriction_hours_pretty"] = pretty(cls.get("restriction_hours", ""))
                a["restriction_reason"] = cls.get("restriction_reason") or None
        if self.quiet:
            a["prewarm"] = True                # built during silent pre-warm: not a new arrival (UI cadence ignores it)
        if extra:
            a.update(extra)
        d = self.decisions.get(aid)
        if d:
            a["decision"] = d; a["status"] = "decided"
            if self.source == "live" and d.get("at"):
                a["_dec_t"] = datetime.fromisoformat(d["at"].replace("Z", "+00:00"))
        self.alerts[aid] = a
        self.open[vid][spec["kind"]] = aid
        self.stats[spec["kind"]] += 1
        self.publish("alert", self.public(a), a["city"])
        return a

    @staticmethod
    def public(a):
        return {k: v for k, v in a.items() if not k.startswith("_")}

    def resolve(self, aid, t, result, correct, via=None, summary=None):
        a = self.alerts.get(aid)
        if not a or a["status"] == "resolved":
            return
        a["outcome"] = {"checked_at": self.disp(t), "result": result, "correct": correct, "via": via,
                        "summary": summary or result.replace("_", " ")}
        a["_out_t"] = t
        if a.get("decision"):
            self._eval_decision(a)
            if not a.get("test"):
                self.store.update_outcome(aid, a["outcome"])
        a["status"] = "resolved"
        ok = self.open.get(a["vehicle"]["miles_id"], {})
        if ok.get(a["kind"]) == aid:
            del ok[a["kind"]]
        self.publish("alert", self.public(a), a["city"])

    def _eval_decision(self, a):
        """Decision outcome per kind (written into outcome.decision_good / decision_summary).
        restricted/far: good if the car left (customer rental or MILES relocation) before a tow / while the risk lasted;
                        bad if it stayed through the active restriction (or 12 h) or was moved without a ride (tow proxy).
        stranding + intervention (relocate/discount/dispatch/notify): good if rented within 2 h of the decision.
        stranding + accept: good if it was rented anyway (no 12 h idle).  fleet kinds: not scored."""
        o, d = a.get("outcome"), a.get("decision")
        if not o or not d:
            return
        kind, via, action = a["kind"], o.get("via"), d["action"]
        good, why = None, None
        if kind in ("restricted_active", "far_from_legal"):
            if via in ("customer", "ops"):
                good, why = True, ("car left – rented by a customer, risk ended" if via == "customer" else "car relocated by MILES ops, risk ended")
            elif via == "tow":
                good, why = False, "moved without a ride (tow / Umsetzung proxy)"
            elif o["result"] == "still_parked":
                good, why = False, "still parked while restriction active" if kind == "restricted_active" else "still parked after 12 h"
        elif kind == "stranding":
            dec_t, out_t = a.get("_dec_t"), a.get("_out_t")
            if action == "accept":
                if via == "customer":
                    good, why = True, "rented anyway – accepting was right"
                elif o["result"] == "idle_12h_plus":
                    good, why = False, "sat idle >12 h"
            else:
                if via == "customer" and dec_t is not None and out_t is not None and out_t >= dec_t:
                    m = (out_t - dec_t).total_seconds() / 60
                    good, why = (m <= 120), (f"rented {m:.0f} min after the decision" if m <= 120 else f"rented only {m/60:.1f} h after the decision")
                elif via == "customer" and dec_t is not None and out_t is not None:
                    why = "rented before the decision took effect"
                elif o["result"] == "idle_12h_plus":
                    good, why = False, "still idle 12 h after ride end"
                elif via in ("ops", "tow"):
                    why = "moved without a customer ride"
        o["decision_good"] = good
        o["decision_summary"] = why

    def _close_park_alerts(self, vid, t, result, minutes, via):
        """Car left its parking spot. Prediction correctness: stranding = idle >12 h happened (never true here, because
        alerts still open at 12 h are resolved by recheck); restricted/far = risk materialised (tow proxy)."""
        mtxt = f"{minutes:.0f} min" if minutes is not None and minutes < 120 else (f"{minutes/60:.1f} h" if minutes is not None else "?")
        summ = {"customer": f"rented again after {mtxt}", "ops": f"relocated by MILES ops after {mtxt}",
                "tow": f"moved without a ride after {mtxt} (tow proxy)"}.get(via, result.replace("_", " "))
        for kind in PARK_KINDS:
            aid = self.open.get(vid, {}).get(kind)
            if not aid:
                continue
            if kind == "stranding":
                correct = minutes is not None and minutes > 720
            else:
                correct = via == "tow"
            self.resolve(aid, t, result, correct, via, summ)

    # ---- parking events ----
    def classify(self, lat, lon):
        return self.geo.classify([lat], [lon])[0]

    def strand_alert(self, pid, vid, t, lat, lon, cls, p, scorer="fallback", inputs=None, discounted=None):
        """Stranding alert (= Relocate move candidate) when p >= the scorer's threshold for that model."""
        if p is None or p != p or p < 0:
            return None
        self.p_hist.append(p)
        thr = self.scorer.threshold(scorer) if self.scorer else self.model.threshold
        if p < thr:
            return None
        v = self.vehicle(vid)
        if inputs is None:
            tl = t.astimezone(BER)
            inputs = {"hour": tl.hour, "weekday": tl.strftime("%a"), "charge": v.get("charge"), "size": v.get("size_class"), "car": v.get("model"),
                      "electric": bool(v.get("electric")), "damage_count": v.get("damage") or 0,
                      "km_from_centre": round(math.hypot((lat - 52.5163) * 111.2, (lon - 13.3777) * 67.8), 1), "discounted": discounted}
        return self._new_alert(f"{self.prefix}{pid}_st", t, vid, lat, lon, cls, rules.stranding(cls, p, thr, None),
                               extra={"model": scorer, "inputs": inputs})

    def park(self, pid, vid, t, lat, lon, kind, cls=None, p_strand=None, alerts=True, scorer="TabPFN"):
        """kind: ride | booking_cancel | initial | moved | other. Berlin vehicles only."""
        if lat is None or lon is None:
            return None
        cls = cls or self.classify(lat, lon)
        pk = Park(pid, vid, t, lat, lon, cls, kind)
        self.parked[vid] = pk
        if pk.zone:
            self.zone_info.setdefault(pk.zone, (pk.fee, cls.get("paid_zone_hours")))
        if kind == "ride":
            self.ride_ends[t.astimezone(BER).date()] += 1
        made = []
        if alerts and kind in ("ride", "booking_cancel"):
            tl = t.astimezone(BER)
            if pk.restricted_now(tl):
                if self._new_alert(f"{self.prefix}{pid}_ra", t, vid, lat, lon, cls, rules.restricted_active(cls, 0.0, False)):
                    made.append("restricted_active")
            if pk.far():
                if self._new_alert(f"{self.prefix}{pid}_ff", t, vid, lat, lon, cls, rules.far_from_legal(cls)):
                    made.append("far_from_legal")
            if kind == "ride" and self.model is not None:
                if p_strand is None and self.strand_queue is not None and datetime.now(UTC) - t < timedelta(hours=3):
                    self.strand_queue.append((pid, vid, t, lat, lon, cls))   # live: scored by the TabPFN micro-batch
                else:
                    if p_strand is None:   # live history (rebuild): GBM
                        v = self.vehicle(vid)
                        feats = self.model.features_for(lat, lon, tl, v.get("charge"), cls, v.get("size_class"), v.get("electric"), v.get("damage") or 0)
                        p_strand, scorer = self.model.predict([feats])[0], "fallback"
                    if self.strand_alert(pid, vid, t, lat, lon, cls, p_strand, scorer):
                        made.append("stranding")
        if kind != "initial":
            self.publish_park(vid, t, pk, kind, made)
        return pk

    def publish_park(self, vid, t, pk, kind, alert_kinds, test=False):
        """Lightweight map event: a car parked (ride end, booking cancel, moved). Same path for live and replay."""
        if self.quiet:
            return
        tl = t.astimezone(BER)
        self.publish("park", {"vid": vid, "lat": round(pk.lat, 5), "lon": round(pk.lon, 5), "kind": kind, "at": self.disp(t),
                              "zone": pk.zone, "billing": pk.billing_now(tl), "alerts": alert_kinds, "test": test}, "BER")

    def cars_snapshot(self):
        """Parked Berlin cars for the map: [vid, lat, lon, billing(0/1)]."""
        tl = self.engine_now().astimezone(BER)
        return [[vid, round(pk.lat, 5), round(pk.lon, 5), 1 if pk.billing_now(tl) else 0] for vid, pk in self.parked.items()]

    def depart(self, vid, t, new_status, pid=None, via=None):
        pk = self.parked.get(vid)
        if pk is None or (pid is not None and pk.pid != pid):
            return
        del self.parked[vid]
        minutes = (t - pk.t0).total_seconds() / 60
        if via is None:
            via = "customer" if (new_status in RIDE_STATUSES or new_status == "BOOKED_BY_USER") else "ops"
        self.publish("depart", {"vid": vid, "lat": round(pk.lat, 5), "lon": round(pk.lon, 5), "via": via}, "BER")
        if via == "customer":
            result = "rented_within_2h" if minutes <= 120 else f"re_rented_after_{int(minutes)}min"
        else:
            result = "moved_without_ride"
        self._close_park_alerts(vid, t, result, minutes, via)

    def moved(self, vid, t, lat, lon, pid):
        pk = self.parked.get(vid)
        if pk is None or lat is None:
            return False
        d = hav_m(pk.lat, pk.lon, lat, lon)
        if d < 150:
            return False
        minutes = (t - pk.t0).total_seconds() / 60
        self._close_park_alerts(vid, t, "moved_without_ride", minutes, "tow")
        self.parked.pop(vid, None)
        self.publish("depart", {"vid": vid, "lat": round(pk.lat, 5), "lon": round(pk.lon, 5), "via": "tow"}, "BER")
        self.park(pid, vid, t, lat, lon, "moved")
        return True

    # ---- periodic ----
    def recheck(self, t):
        """Restriction windows for all parked cars + 12 h outcome checks + stale fleet alerts."""
        tl = t.astimezone(BER)
        for vid, pk in list(self.parked.items()):
            if pk.restricted_now(tl) and "restricted_active" not in self.open.get(vid, {}):
                aid = f"{self.prefix}{pk.pid}_ra"
                if aid not in self.alerts and aid not in self.seen:
                    ph = (t - pk.t0).total_seconds() / 3600
                    switched = pk.kind != "initial" and not active(pk.rwin, pk.t0.astimezone(BER))
                    self._new_alert(aid, t, vid, pk.lat, pk.lon, pk.cls, rules.restricted_active(pk.cls, ph if pk.kind != "initial" else None, switched))
            rs = self.open.get(vid, {}).get("restriction_soon")
            if rs and pk.restricted_now(tl):
                self.resolve(rs, t, "still_parked", True, "none", f"still parked when the restriction started ({tl:%H:%M})")
            elif not rs and pk.rwin is not False and not pk.restricted_now(tl) and "restricted_active" not in self.open.get(vid, {}):
                m = minutes_until_active(pk.rwin, tl, SOON_MIN, 5)
                if m is not None and m > 0:
                    sid = f"{self.prefix}{pk.pid}_rs_{tl:%m%d}"
                    if sid not in self.seen:
                        dl = tl + timedelta(minutes=m)
                        dl = dl.replace(minute=(dl.minute // 5) * 5, second=0, microsecond=0)
                        self._new_alert(sid, t, vid, pk.lat, pk.lon, pk.cls, rules.restriction_soon(pk.cls, m, dl.strftime("%H:%M")),
                                        extra={"deadline_local": dl.strftime("%H:%M"), "deadline_min": m, "_deadline_t": t + timedelta(minutes=m)})
            ra = self.open.get(vid, {}).get("restricted_active")
            if ra and not pk.restricted_now(tl):
                self.resolve(ra, t, "still_parked", True, "none", f"still parked while restriction active (until {tl:%H:%M})")
            elif ra and (t - self.alerts[ra]["_t"]).total_seconds() >= 3 * 3600:
                self.resolve(ra, t, "still_parked", True, "none", "still parked 3 h into an active restriction")
            age_h = (t - pk.t0).total_seconds() / 3600
            if age_h >= 12:
                for kind in PARK_KINDS:
                    aid = self.open.get(vid, {}).get(kind)
                    if aid and (t - self.alerts[aid]["_t"]).total_seconds() >= 12 * 3600:
                        if kind == "stranding":
                            self.resolve(aid, t, "idle_12h_plus", True, "none", "sat idle >12 h after the ride end")
                        else:
                            self.resolve(aid, t, "still_parked", True, "none", "still parked 12 h later")
        # fleet alerts: ops resolve when vehicle is back; expire others after 6 h
        for vid, kinds in list(self.open.items()):
            for kind, aid in list(kinds.items()):
                if kind in ("low_fuel", "damage", "ops"):
                    a = self.alerts[aid]
                    if (t - a["_t"]).total_seconds() > self.fleet_ttl_h * 3600 and not a.get("test"):
                        self.resolve(aid, t, "still_parked", None)
        # memory bound: drop resolved, undecided alerts older than 24 h (engine time) once the store gets large
        if len(self.alerts) > 12000:
            cutoff = t - timedelta(hours=24)
            for aid in [k for k, a in self.alerts.items() if a["status"] == "resolved" and a["_t"] < cutoff and not a.get("decision")]:
                del self.alerts[aid]
        self.now_t = t

    def ledger_tick(self, t, minutes):
        tl = t.astimezone(BER)
        day = tl.date()
        led = self.ledger[day]
        for pk in self.parked.values():
            if pk.billing_now(tl):
                led[pk.zone] += pk.fee * minutes / 60.0
        for d in [d for d in self.ledger if d < day - timedelta(days=2)]:
            del self.ledger[d]
        return day, led

    # ---- fleet events ----
    def fleet(self, eid, vid, t, kind, lat, lon, **kw):
        v = self.vehicle(vid)
        city = v.get("city") or "?"
        if kind == "ops":
            spec = rules.fleet_ops(city, v["plate"], kw["status"])
        elif kind == "low_fuel":
            spec = rules.fleet_low_fuel(city, v["plate"], kw["charge"], v.get("electric"))
        else:
            spec = rules.fleet_damage(city, v["plate"], kw["n"])
        old = self.open.get(vid, {}).get(kind)
        if old:
            return None
        cls = self.parked[vid].cls if vid in self.parked else None
        return self._new_alert(f"{self.prefix}{eid}_{KABBR[kind]}", t, vid, lat, lon, cls, spec)

    def fleet_back(self, vid, t, kind, result="still_parked"):
        aid = self.open.get(vid, {}).get(kind)
        if aid:
            self.resolve(aid, t, result, None)

    # ---- QA test events ----
    def expire_tests(self, max_age_s=600, all_=False):
        """Resolve open QA test alerts older than max_age_s wall-clock seconds (or all of them)."""
        now, t, n = time.time(), self.engine_now(), 0
        for aid, a in list(self.alerts.items()):
            if a.get("test") and a["status"] != "resolved" and (all_ or now - a.get("_real", now) >= max_age_s):
                self.resolve(aid, t, "test_expired", None, "none", "test event cleared")
                n += 1
        return n

    # ---- decisions ----
    def decide(self, aid, action, note, operator, extra=None):
        a = self.alerts.get(aid)
        if a is None:
            return None
        d = {"action": action, "note": note or "", "operator": operator or "ops", "at": iso(datetime.now(UTC))}
        if extra:
            d.update(extra)
        a["decision"] = d
        a["_dec_t"] = self.engine_now()
        if a["status"] == "open":
            a["status"] = "decided"
        if a.get("outcome"):
            self._eval_decision(a)
        self.decisions[aid] = d
        if not a.get("test"):  # QA test events never reach the decision store (log, scorecard, decisions_today)
            self.store.add_decision(self.source, aid, d, self.public(a))
        self.publish("decision", self.public(a), a["city"])
        self.publish("alert", self.public(a), a["city"])
        return a

    # ---- read models ----
    def counters(self, t=None):
        t = t or self.engine_now()
        tl = t.astimezone(BER)
        parked = self.parked.values()
        in_zone = billing = restr = far = 0
        fee_h = 0.0
        for pk in parked:
            if pk.zone:
                in_zone += 1
                if pk.billing_now(tl):
                    billing += 1; fee_h += pk.fee
            if pk.restricted_now(tl):
                restr += 1
            if pk.far():
                far += 1
        open_alerts = [a for a in self.alerts.values() if a["status"] != "resolved" and a["city"] == "BER"]
        midnight = datetime.now(BER).replace(hour=0, minute=0, second=0, microsecond=0)
        c = {"ride_ends_today": self.ride_ends.get(tl.date(), 0), "cars_parked_now": len(self.parked),
             "cars_in_paid_zone_now": in_zone, "fees_eur_today": round(sum(self.ledger.get(tl.date(), {}).values()), 2),
             "fees_eur_per_hour_now": round(fee_h, 2), "restricted_active_now": restr, "far_from_legal_now": far,
             "stranding_risk_now": sum(1 for a in open_alerts if a["kind"] == "stranding" and not a.get("test")),
             "open_alerts": len(open_alerts),
             "decisions_today": self.store.count_decisions(self.source, midnight.astimezone(UTC)),
             # additive
             "cars_billable_now": billing, "clock_speed": 1.0,
             "last_event_s": round(time.time() - self.last_event_real, 1) if self.last_event_real else None}
        return c

    def telemetry(self):
        import numpy as np
        p = np.array(self.p_hist) if self.p_hist else None
        first = min((a["_t"] for a in self.alerts.values()), default=None)
        return {"alerts_emitted": dict(self.stats), "alerts_in_memory": len(self.alerts), "first_alert_at": self.disp(first) if first else None,
                "stranding_scores": None if p is None else {"n": int(len(p)), "p50": round(float(np.median(p)), 3),
                                                             "p90": round(float(np.quantile(p, 0.9)), 3), "max": round(float(p.max()), 3),
                                                             "share_above_threshold": round(float((p >= self.model.threshold).mean()), 3)}}

    def stranding_score(self):
        cutoff = self.engine_now() - timedelta(hours=12)
        st = [a for a in self.alerts.values() if a["kind"] == "stranding" and a.get("outcome") and a["_t"] <= cutoff and not a.get("test")]
        return {"live_checked": len(st), "live_correct": sum(1 for a in st if a["outcome"]["correct"]),
                "basis": "stranding alerts at least 12 h old: correct = car actually sat idle >12 h"}

    def scorecard(self):
        dec = [a for a in self.alerts.values() if a.get("decision") and not a.get("test")]
        known = [a for a in dec if a.get("outcome") and a["outcome"].get("decision_good") is not None]
        V = rules.VALIDATION
        return {"stranding": dict(validation_precision=V["precision_top10"], validation_auc=V["auc"], base_rate=V["base_rate"],
                                  threshold=V["threshold"], **self.stranding_score()),
                "decisions": {"total": len(dec), "outcome_known": len(known), "good": sum(1 for a in known if a["outcome"]["decision_good"])}}

    def ledger_view(self, t=None):
        t = t or self.engine_now()
        tl = t.astimezone(BER)
        led = self.ledger.get(tl.date(), {})
        cars = defaultdict(int)
        for pk in self.parked.values():
            if pk.zone:
                cars[pk.zone] += 1
        zones = set(led) | set(cars)
        out = []
        for z in zones:
            fee, hrs = self.zone_info.get(z, (None, ""))
            w = parse(hrs or "")
            out.append({"zone": z, "fee_eur_h": fee, "cars_now": cars.get(z, 0), "eur_today": round(led.get(z, 0.0), 2),
                        "hours": hrs, "paid_now": bool(hrs) and w not in (None, "unparsed") and active(w, tl)})
        out.sort(key=lambda r: (-r["eur_today"], -r["cars_now"]))
        return {"zones": out}

    def open_alerts(self, city="BER", limit=300):
        al = [a for a in self.alerts.values() if a["status"] != "resolved" and (city in (None, "ALL") or a["city"] == city)]
        al.sort(key=lambda a: a["_t"], reverse=True)
        return [self.public(a) for a in al[:limit]]

    def upcoming_restrictions(self, t, horizon=120):
        tl = t.astimezone(BER)
        out = []
        for vid, pk in self.parked.items():
            if pk.rwin is False or pk.restricted_now(tl):
                continue
            m = minutes_until_active(pk.rwin, tl, horizon)
            if m is not None:
                out.append((vid, m, pk))
        return out
