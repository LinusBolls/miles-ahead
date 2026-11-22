"""Replay source: Berlin June 2024 parking periods after customer rides, played at `speed`x from a busy weekday
moment (default Tue 4 Jun 2024 10:00 Berlin). Only daytime is played (09:00-21:00 sim time, Sundays skipped): at 21:00
the replay jumps to the next day's 09:00. Every (re)start pre-warms silently: the preceding hours are processed without
SSE events (alerts built then carry prewarm=true), so the inbox, ledger and "today" counters are plausible from the first
second and there is no startup burst. Outcomes are known from the data (rented / idle >12 h / moved without ride).
Same alert schema as live. Data: geo/replay_berlin_2024-06.npz (build_replay.py)."""
import asyncio, json, logging, os, time
from datetime import datetime, timedelta

import numpy as np

from .engine import BER, UTC, Engine, iso
from .windows import parse, active

log = logging.getLogger("replay")
H = 3600 * 10**9
START = datetime.fromisoformat(os.environ.get("REPLAY_START", "2024-06-04T10:00")).replace(tzinfo=BER)
DAY_START_H = int(os.environ.get("REPLAY_DAY_START_H", "9"))
DAY_END_H = int(os.environ.get("REPLAY_DAY_END_H", "21"))
PREWARM_H = float(os.environ.get("REPLAY_PREWARM_H", "3"))
SPEED_MIN, SPEED_MAX = 0.5, 60.0


def dt(ns):
    return datetime.fromtimestamp(int(ns) / 1e9, UTC)


def to_ns(t):
    return int(round(t.timestamp() * 1e6)) * 1000


class ReplayEngine(Engine):
    rs = None
    fleet_ttl_h = 0.5   # replay has no "back from ops" rows, so fleet alerts would otherwise pile up for 6 h

    def stranding_score(self):
        """Outcome is known from the data: every flagged ride end (p >= threshold) whose 12 h window has fully elapsed
        in sim time (ride ends 12-36 h before sim-now); correct = it really sat idle >12 h. In-sample (model fit on June)."""
        rs = self.rs
        if rs is None or rs.D0 is None:
            return {"live_checked": 0, "live_correct": 0}
        Dn = to_ns(rs.data_now())
        lo, hi = np.searchsorted(rs.t0, Dn - 36 * H), np.searchsorted(rs.t0, Dn - 12 * H, side="right")
        if "p_tabpfn" in rs.c and self.scorer:
            p = rs.c["p_tabpfn"][lo:hi]; sel = p >= self.scorer.threshold("TabPFN")
        else:
            p = rs.c["p_strand"][lo:hi]; sel = p >= self.model.threshold
        y = rs.c["parked_hours"][lo:hi][sel] > 12
        return {"live_checked": int(sel.sum()), "live_correct": int(y.sum()),
                "basis": "replay: flagged ride ends 12–36 h ago (sim time); correct = really idle >12 h (in-sample)"}

    def disp(self, t):
        rs = self.rs
        if rs is None or rs.D0 is None:
            return iso(t)
        return iso(datetime.fromtimestamp(rs.real0, UTC) + (t - rs.D0) / rs.speed)

    def engine_now(self):
        rs = self.rs
        return rs.data_now() if rs and rs.D0 is not None else datetime.now(UTC)

    def counters(self, t=None):
        c = super().counters(t)
        rs = self.rs
        if rs is not None and rs.D0 is not None:
            D = rs.data_now()
            c.update(clock_speed=rs.speed, sim_time=iso(D), sim_now_local=D.astimezone(BER).strftime("%a %d %b %H:%M"))
        return c


class ReplaySource:
    def __init__(self, engine, npz_path, speed=30.0):
        self.e = engine
        engine.rs = self
        self.speed = float(speed)
        z = np.load(npz_path)
        self.c = {k: z[k] for k in z.files}
        self._smooth_scrape_batches()
        meta = json.load(open(os.path.join(os.path.dirname(npz_path), "replay_meta.json")))
        self.vmeta = {int(k): v for k, v in meta["vehicles"].items()}
        self.zones = meta["zones"]        # [name, fee, hours]
        self.zwin = [parse(h or "") for _, _, h in self.zones]
        self.statuses = meta["statuses"]
        self.t0 = self.c["t0"]; self.t1 = self.c["t1"]
        assert np.all(np.diff(self.t0) >= 0), "replay data must be sorted by t0"
        self.end_order = np.argsort(self.t1, kind="stable")
        self.t1_sorted = self.t1[self.end_order]
        self.data_start, self.data_end = dt(self.t0.min()), dt(self.t0.max())
        self.D0 = None; self.real0 = None; self.Dprev = None
        self.epoch = 0
        self.next_recheck = None
        self.ok = False
        self.loops = 0
        self.pending_restart = None
        self.row_errors = 0

    def _smooth_scrape_batches(self, jit_s=540, seed=42):
        """The 2024 scraper polled about every 9 min, so ride ends and departures arrive in bursts (~100 in one minute,
        then ~8 quiet minutes). A real event happened somewhere in the polling interval before it was seen: move each
        t0/t1 back by a seeded random share of that interval. The move is capped at half the gap to the vehicle's previous
        event, so a car's own park/ride order never changes. Durations change by at most a few minutes."""
        c = self.c
        t0, t1, vid = c["t0"].astype(np.int64), c["t1"].astype(np.int64), c["vehicle_id"]
        n, J, MIN = len(t0), int(jit_s * 1e9), np.iinfo(np.int64).min
        o = np.lexsort((t0, vid))
        prev_t1 = np.full(n, MIN, dtype=np.int64)
        same = vid[o][1:] == vid[o][:-1]
        prev_t1[o[1:]] = np.where(same, t1[o][:-1], MIN)
        gap0 = np.where(prev_t1 == MIN, 2 * J, np.maximum(0, t0 - np.where(prev_t1 == MIN, 0, prev_t1)))
        rng = np.random.default_rng(seed)
        t0n = t0 - (rng.random(n) * np.minimum(J, gap0 // 2)).astype(np.int64)
        t1n = t1 - (rng.random(n) * np.minimum(J, np.maximum(0, t1 - t0) // 2)).astype(np.int64)
        c["t0"], c["t1"] = t0n, np.maximum(t1n, t0n + 1)
        perm = np.argsort(c["t0"], kind="stable")
        for k in list(c):
            c[k] = c[k][perm]

    def data_now(self):
        return self.D0 + timedelta(seconds=(time.time() - self.real0) * self.speed)

    def set_speed(self, speed):
        """Change speed without restarting: re-anchor so sim time stays continuous."""
        speed = max(SPEED_MIN, min(SPEED_MAX, float(speed)))
        if self.D0 is not None:
            D = self.data_now()
            self.D0, self.real0 = D, time.time()
        self.speed = speed
        return speed

    def next_day_start(self, D):
        """09:00 Berlin of the next day that is not a Sunday (most paid zones are free on Sundays); wraps to START
        when the data runs out."""
        dl = D.astimezone(BER)
        day = dl.date() + timedelta(days=1)
        while day.weekday() == 6:
            day += timedelta(days=1)
        nxt = datetime(day.year, day.month, day.day, DAY_START_H, tzinfo=BER).astimezone(UTC)
        if nxt + timedelta(hours=DAY_END_H - DAY_START_H) > self.data_end:
            self.loops += 1
            return START.astimezone(UTC)
        return nxt

    def vehicle_from_row(self, i):
        vid = int(self.c["vehicle_id"][i])
        v = self.e.vehicle(vid)
        m = self.vmeta.get(vid)
        if m:
            v.update(plate=m[0], model=m[1], size_class=m[2], electric=bool(m[3]))
        v["city"] = "BER"
        ch = int(self.c["ch1"][i]); v["charge"] = ch if ch >= 0 else None
        v["damage"] = int(self.c["prior_damage"][i])
        return vid

    def start(self, speed=None, at=None):
        """(Re)start at sim time `at` (default START). Silent pre-warm: seed the cars parked at at-PREWARM_H, then
        process PREWARM_H hours of ride ends, departures, re-checks and ledger ticks with SSE muted."""
        if speed:
            self.speed = max(SPEED_MIN, min(SPEED_MAX, float(speed)))
        e = self.e
        t_wall = time.time()
        e.reset()
        e.decisions = e.store.latest_decisions("replay")
        self.epoch = int(time.time()) % 1000000
        e.prefix = f"r{self.epoch}_"
        self.D0 = (at or START).astimezone(UTC)
        self.real0 = time.time()
        S0 = self.D0 - timedelta(hours=PREWARM_H)
        S0n = to_ns(S0)
        self.next_recheck = None
        e.quiet = True
        try:
            idx = np.where((self.t0 <= S0n) & (self.t1 > S0n) & (self.t0 >= S0n - 72 * H))[0]
            self._park_rows(idx, alerts=False)
            sl = S0.astimezone(BER)
            mid = sl.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
            midn = to_ns(mid)
            e.ride_ends.clear()
            e.ride_ends[sl.date()] = int(((self.t0 >= midn) & (self.t0 <= S0n)).sum())
            self._backfill_ledger(mid, S0)
            e.recheck(S0)
            self.next_recheck = S0.replace(second=0, microsecond=0, minute=(S0.minute // 5) * 5) + timedelta(minutes=5)
            self.Dprev = S0
            self._advance(S0, self.D0)
            self.Dprev = self.D0
        finally:
            e.quiet = False
        self.real0 = time.time()   # sim clock starts now at D0 (pre-warm took real time)
        self.ok = True
        log.info("replay start: D0=%s speed=%sx parked=%d alerts=%d open=%d prewarm=%.1fs", self.D0, self.speed, len(e.parked),
                 len(e.alerts), sum(1 for a in e.alerts.values() if a["status"] != "resolved"), time.time() - t_wall)
        e.publish("reset", {"reason": "replay_start", "sim_time": iso(self.D0), "speed": self.speed}, None)

    def _backfill_ledger(self, a, b):
        """Today's fee ledger up to the replay start, integrated in 5-min steps (same rule as the live 60 s tick)."""
        zc = self.c["zone"]
        an, bn = to_ns(a), to_ns(b)
        cand = np.where((self.t0 < bn) & (self.t1 > an) & (self.t0 >= an - 72 * H) & (zc >= 0))[0]
        led = self.e.ledger[b.astimezone(BER).date()]
        led.clear()
        for z, fee, hrs in self.zones:
            self.e.zone_info.setdefault(z, (fee, hrs))
        t = a
        while t < b:
            tn = to_ns(t)
            tl = t.astimezone(BER)
            act = cand[(self.t0[cand] <= tn) & (self.t1[cand] > tn)]
            if len(act):
                codes, counts = np.unique(zc[act], return_counts=True)
                for code, n in zip(codes, counts):
                    w = self.zwin[code]
                    if w not in (None, "unparsed") and active(w, tl):
                        led[self.zones[code][0]] += self.zones[code][1] * n * 5 / 60
            t += timedelta(minutes=5)

    def _park_rows(self, idx, alerts):
        if len(idx) == 0:
            return
        cls_list = self.e.geo.classify(self.c["lat"][idx], self.c["lon"][idx])
        for i, cls in zip(idx, cls_list):
            try:
                self._park_one(int(i), cls, alerts)
            except Exception:
                self.row_errors += 1
                if self.row_errors < 20:
                    log.exception("replay row %s failed", i)

    def _park_one(self, i, cls, alerts):
        c = self.c
        vid = self.vehicle_from_row(i)
        t = dt(self.t0[i])
        if alerts:
            self._tick_to(t)
        # TabPFN score precomputed offline (build_tabpfn.py, out-of-sample); GBM only if it is missing
        pt = float(c["p_tabpfn"][i]) if "p_tabpfn" in c else -1.0
        p, scorer = (pt, "TabPFN") if pt >= 0 else (float(c["p_strand"][i]), "fallback")
        lat, lon = float(c["lat"][i]), float(c["lon"][i])
        self.e.park(i, vid, t, lat, lon, "ride", cls=cls, p_strand=p, alerts=alerts, scorer=scorer)
        if alerts:
            if bool(c["damaged"][i]):
                self.e.fleet(i, vid, t, "damage", lat, lon, n=int(c["prior_damage"][i]) + 1)
            ch = int(c["ch1"][i])
            if 0 <= ch < 10:
                self.e.fleet(i, vid, t, "low_fuel", lat, lon, charge=float(ch))

    def _end_rows(self, order_idx):
        c = self.c
        for i in order_idx:
            i = int(i)
            try:
                vid = int(c["vehicle_id"][i])
                t = dt(self.t1[i])
                self._tick_to(t)
                pk = self.e.parked.get(vid)
                if pk is None or pk.pid != i:
                    continue
                ops = bool(c["ops_next"][i]); tow = bool(c["tow_proxy"][i])
                if ops:
                    self.e.fleet(i, vid, t, "ops", pk.lat, pk.lon, status=self.statuses[int(c["next_status"][i])] or "IN_OPS")
                via = "tow" if tow else ("ops" if ops else "customer")
                self.e.depart(vid, t, "USER_IN_RIDE" if via == "customer" else "IN_OPS", pid=i, via=via)
            except Exception:
                self.row_errors += 1
                if self.row_errors < 20:
                    log.exception("replay end row %s failed", i)

    def _tick_to(self, t):
        if self.next_recheck is None:
            return
        while self.next_recheck <= t:
            self.e.recheck(self.next_recheck)
            self.e.ledger_tick(self.next_recheck, 5)
            self.next_recheck += timedelta(minutes=5)

    def _advance(self, A, B):
        """Process every park start (t0) and end (t1) in (A, B] in time order, then tick re-checks/ledger to B."""
        a, b = to_ns(A), to_ns(B)
        if b <= a:
            return
        i0, i1 = np.searchsorted(self.t0, a, side="right"), np.searchsorted(self.t0, b, side="right")
        j0, j1 = np.searchsorted(self.t1_sorted, a, side="right"), np.searchsorted(self.t1_sorted, b, side="right")
        ev = [(int(self.t0[i]), 0, i) for i in range(i0, i1)] + [(int(self.t1[i]), 1, int(i)) for i in self.end_order[j0:j1]]
        ev.sort()
        buf = []
        for _, typ, i in ev:
            if typ == 0:
                buf.append(i)
            else:
                if buf:
                    self._park_rows(np.array(buf), True); buf = []
                self._end_rows([i])
        if buf:
            self._park_rows(np.array(buf), True)
        self._tick_to(B)

    def step(self):
        D = self.data_now()
        if D > self.data_end:
            self.loops += 1
            self.start()
            return
        if D.astimezone(BER).hour >= DAY_END_H:
            self.start(at=self.next_day_start(D))   # jump over the night (and Sundays)
            return
        if to_ns(D) <= to_ns(self.Dprev):
            return
        A, self.Dprev = self.Dprev, D  # advance first: a bad row must never freeze the replay
        self._advance(A, D)

    async def run(self):
        while True:
            try:
                if self.D0 is None or self.pending_restart is not None:
                    sp = self.pending_restart
                    self.pending_restart = None
                    self.start(speed=sp)
                self.step()
                self.ok = True
            except Exception:
                self.ok = False
                log.exception("replay step failed")
                await asyncio.sleep(2)
            await asyncio.sleep(0.25)  # small steps: events arrive spread out like live, not in 1 s batches

    def status(self):
        D = self.data_now() if self.D0 else None
        return {"speed": self.speed, "data_time": iso(D), "sim_now_local": D.astimezone(BER).strftime("%a %d %b %Y %H:%M") if D else None,
                "start": iso(START), "daytime": [DAY_START_H, DAY_END_H], "prewarm_h": PREWARM_H,
                "data_range": [iso(self.data_start), iso(self.data_end)], "loops": self.loops, "epoch": self.epoch, "ok": self.ok,
                "row_errors": self.row_errors}

    def vehicle_detail(self, vid, limit=20):
        c = self.c
        idx = np.where(c["vehicle_id"] == vid)[0]
        if self.D0 is not None:
            idx = idx[self.t0[idx] <= to_ns(self.data_now())]
        idx = idx[-limit:][::-1]
        cls = self.e.geo.classify(c["lat"][idx], c["lon"][idx]) if len(idx) else []
        out = []
        for i, cl in zip(idx, cls):
            ch = int(c["ch1"][i]); p = float(c["p_strand"][i])
            out.append({"parked_from": self.e.disp(dt(self.t0[i])), "data_time": iso(dt(self.t0[i])),
                        "parked_hours": round(float(c["parked_hours"][i]), 2), "lat": float(c["lat"][i]), "lon": float(c["lon"][i]),
                        "area_type": cl["area_type"], "street": cl["street"], "paid_zone": cl["paid_zone"] or None,
                        "charge": ch if ch >= 0 else None, "next_status": self.statuses[int(c["next_status"][i])],
                        "moved_without_ride": bool(c["tow_proxy"][i]), "p_strand": round(p, 4) if p >= 0 else None})
        return out
