"""Live source: rebuilds state from the full vehicle_changes history at startup, then polls incrementally by id."""
import asyncio, logging, re, time
from datetime import datetime, timedelta, timezone

import psycopg

from .engine import BER, RIDE_STATUSES, UTC, hav_m

log = logging.getLogger("live")
OPS_RE = re.compile(r"(OPS|REPAIR|CLAIMS|LOGISTICS|VRC|BODYSHOP|RELOCATION)")
COLS = 'id, at, "milesId", op, old_status, new_status, old_charge, new_charge, old_damage, new_damage, latitude, longitude'
VEH_SQL = '''SELECT v."milesId", v."licensePlate", m.name, m.electric, s.name, c."milesId"
             FROM "MilesVehicle" v JOIN "MilesVehicleModel" m ON m.id = v."modelId"
             LEFT JOIN "MilesVehicleSize" s ON s.id = m."sizeId" LEFT JOIN "MilesCity" c ON c.id = v."firstFoundCityId"'''


def mask_plate(pl):
    if not pl:
        return "••"
    pl = pl.strip()
    pre, _, num = pl.rpartition(" ")
    if not pre:
        return pl[:-2] + "••" if len(pl) > 2 else "••"
    return f"{pre} ••{num[-2:]}"


def floor_to(t, minutes):
    return t.replace(second=0, microsecond=0, minute=(t.minute // minutes) * minutes)


class LiveSource:
    def __init__(self, engine, dsn):
        self.e, self.dsn = engine, dsn
        self.conn = None
        self.cursor = 0
        self.last_change_at = None
        self.db_lag_s = None
        self.ok = False
        self.error = None
        self.next_recheck = None
        self.next_ledger = None
        self.rebuilt = False
        self.rows_total = 0
        self.last_poll = None
        self.ber_last_change_at = None
        self.ber_last_ride_end_at = None

    # ---- db ----
    def _conn(self):
        if self.conn is None or self.conn.closed:
            self.conn = psycopg.connect(self.dsn, autocommit=True, connect_timeout=5)
        return self.conn

    def _q(self, sql, args=()):
        try:
            with self._conn().cursor() as cur:
                cur.execute(sql, args)
                return cur.fetchall()
        except psycopg.OperationalError:
            self.conn = None
            raise

    def refresh_vehicles(self):
        rows = self._q(VEH_SQL)
        for vid, plate, model, electric, size, city in rows:
            v = self.e.vehicle(vid)
            v.update(plate=mask_plate(plate), model=model, electric=bool(electric), size_class=size, city=city)
        return len(rows)

    # ---- processing ----
    def _tick_to(self, t, ledger_step):
        e = self.e
        if self.next_recheck is None:
            self.next_recheck = floor_to(t, 5) + timedelta(minutes=5)
            self.next_ledger = floor_to(t, ledger_step) + timedelta(minutes=ledger_step)
        while self.next_ledger <= t or self.next_recheck <= t:
            if self.next_ledger <= self.next_recheck:
                day, led = e.ledger_tick(self.next_ledger, ledger_step)
                self.next_ledger += timedelta(minutes=ledger_step)
            else:
                e.recheck(self.next_recheck)
                self.next_recheck += timedelta(minutes=5)

    def process(self, rows, ledger_step):
        e = self.e
        for (cid, at, vid, op, os_, ns, oc, nc, od, nd, lat, lon) in rows:
            self._tick_to(at, ledger_step)
            v = e.vehicle(vid)
            if nc is not None:
                v["charge"] = int(round(nc))
            if nd is not None:
                v["damage"] = nd
            if v.get("city") == "BER":
                self.ber_last_change_at = at
                if ns == "DEPLOYED_FOR_RENTAL" and os_ in RIDE_STATUSES:
                    self.ber_last_ride_end_at = at
                if ns == "DEPLOYED_FOR_RENTAL":
                    pk = e.parked.get(vid)
                    if pk is not None:
                        if os_ == "BOOKED_BY_USER":
                            pk.booked_at = None
                        if os_ in RIDE_STATUSES:  # missed the departure row
                            e.depart(vid, at, os_); e.park(cid, vid, at, lat, lon, "ride")
                        elif (lat is not None and nc is not None and oc is not None and nc < oc
                              and hav_m(pk.lat, pk.lon, lat, lon) >= 150):
                            # moved AND fuel dropped: an undetected customer ride, not a tow (tow proxy needs fuel not lower)
                            e.depart(vid, at, "USER_IN_RIDE"); e.park(cid, vid, at, lat, lon, "ride")
                        else:
                            e.moved(vid, at, lat, lon, cid)
                    else:
                        if op == "INSERT":
                            kind = "initial"
                        elif os_ in RIDE_STATUSES:
                            kind = "ride"
                        elif os_ == "BOOKED_BY_USER":
                            kind = "booking_cancel"
                        else:
                            kind = "other"
                        e.park(cid, vid, at, lat, lon, kind)
                elif ns == "BOOKED_BY_USER":
                    pk = e.parked.get(vid)
                    if pk is not None:
                        pk.booked_at = at
                elif vid in e.parked:
                    e.depart(vid, at, ns)
            if op == "UPDATE":
                if ns and ns != os_ and OPS_RE.search(ns):
                    e.fleet(cid, vid, at, "ops", lat, lon, status=ns)
                if ns and os_ and OPS_RE.search(os_) and not OPS_RE.search(ns):
                    e.fleet_back(vid, at, "ops")
                if nc is not None and nc < 20 and (oc is None or oc >= 20):
                    e.fleet(cid, vid, at, "low_fuel", lat, lon, charge=nc)
                elif nc is not None and nc >= 20 and oc is not None and oc < 20:
                    e.fleet_back(vid, at, "low_fuel")
                if nd is not None and nd > (od or 0):
                    e.fleet(cid, vid, at, "damage", lat, lon, n=nd)
            self.cursor = cid
            self.last_change_at = at
            e.last_data_t = at
        self.rows_total += len(rows)

    async def _fetch(self, sql, args=()):
        return await asyncio.to_thread(self._q, sql, args)

    async def rebuild(self):
        """Fetch in a worker thread, process on the event loop (single writer, no locking needed)."""
        t = time.time()
        await asyncio.to_thread(self.refresh_vehicles)
        self.e.decisions = self.e.store.latest_decisions(self.e.source)
        while True:
            rows = await self._fetch(f"SELECT {COLS} FROM vehicle_changes WHERE id > %s ORDER BY id LIMIT 5000", (self.cursor,))
            if not rows:
                break
            if any(self.e.vehicles.get(r[2], {}).get("city") is None for r in rows):
                await asyncio.to_thread(self.refresh_vehicles)
            self.process(rows, ledger_step=5)
            await asyncio.sleep(0)
        now = datetime.now(UTC)
        self._tick_to(now, 5)
        self.next_ledger = floor_to(now, 1) + timedelta(minutes=1)
        self.e.recheck(now)
        self.rebuilt = True
        log.info("live rebuild: %d rows, cursor %d, %d parked, %d alerts in %.1fs", self.rows_total, self.cursor,
                 len(self.e.parked), len(self.e.alerts), time.time() - t)

    async def poll(self):
        rows = await self._fetch(f"SELECT {COLS} FROM vehicle_changes WHERE id > %s ORDER BY id LIMIT 5000", (self.cursor,))
        if rows:
            if any(self.e.vehicles.get(r[2], {}).get("city") is None for r in rows):
                await asyncio.to_thread(self.refresh_vehicles)
            self.process(rows, ledger_step=1)
        r = await self._fetch("SELECT max(at) FROM vehicle_changes")
        now = datetime.now(UTC)
        if r and r[0][0]:
            self.last_change_at = r[0][0]
            self.db_lag_s = round((now - r[0][0]).total_seconds(), 1)
        self._tick_to(now, 1)
        self.last_poll = now
        return len(rows)

    async def run(self, interval=5):
        while not self.rebuilt:
            try:
                await self.rebuild()
                self.ok, self.error = True, None
            except Exception as ex:  # db down: retry from scratch
                self.ok, self.error = False, f"{type(ex).__name__}: {str(ex)[:200]}"
                log.exception("live rebuild failed")
                self.e.reset(); self.cursor = 0; self.rows_total = 0; self.next_recheck = None; self.next_ledger = None
                await asyncio.sleep(15)
        last_veh = time.time()
        last_led_save = 0
        while True:
            try:
                await self.poll()
                if time.time() - last_veh > 300:
                    await asyncio.to_thread(self.refresh_vehicles); last_veh = time.time()
                if time.time() - last_led_save > 60:
                    day = datetime.now(UTC).astimezone(BER).date()
                    self.e.store.save_ledger("live", day, dict(self.e.ledger.get(day, {}))); last_led_save = time.time()
                self.ok, self.error = True, None
            except Exception as ex:
                self.ok, self.error = False, f"{type(ex).__name__}: {str(ex)[:200]}"
                log.exception("live poll failed")
            await asyncio.sleep(interval)

    def status(self):
        """ok | starting | error | stale (no Berlin updates for 5 min or no Berlin ride end for 15 min)."""
        now = datetime.now(UTC)
        if not self.rebuilt:
            st, msg = "starting", "rebuilding state from vehicle_changes"
        elif self.error:
            st, msg = "error", self.error
        else:
            ch = (now - self.ber_last_change_at).total_seconds() if self.ber_last_change_at else None
            re_ = (now - self.ber_last_ride_end_at).total_seconds() if self.ber_last_ride_end_at else None
            if ch is None or ch > 300 or re_ is None or re_ > 900:
                last = self.ber_last_ride_end_at.astimezone(BER).strftime("%H:%M") if self.ber_last_ride_end_at else "never"
                st, msg = "stale", f"No live Berlin data: last ride end seen {last} (Berlin time). The scraper is stopped or soft-blocked by MILES; figures are frozen – use replay."
            else:
                st, msg = "ok", None
        return {"status": st, "message": msg,
                "ber_last_change_at": self.ber_last_change_at.isoformat() if self.ber_last_change_at else None,
                "ber_last_ride_end_at": self.ber_last_ride_end_at.isoformat() if self.ber_last_ride_end_at else None,
                "ber_freshness_s": round((now - self.ber_last_change_at).total_seconds(), 1) if self.ber_last_change_at else None}

    def health(self):
        return {"ok": self.ok and self.rebuilt, "status": self.status()["status"], "db_lag_s": self.db_lag_s, "last_change_at": self.last_change_at.isoformat() if self.last_change_at else None,
                "cursor": self.cursor, "rows_processed": self.rows_total, "error": self.error,
                "ber_last_change_at": self.ber_last_change_at.isoformat() if self.ber_last_change_at else None,
                "ber_last_ride_end_at": self.ber_last_ride_end_at.isoformat() if self.ber_last_ride_end_at else None}

    def discounted(self, vids):
        """Current discount flag per vehicle (TabPFN feature); vehicle_changes has no discount column."""
        if not vids:
            return {}
        rows = self._q('SELECT "milesId", discounted FROM "MilesVehicleLastKnown" WHERE "milesId" = ANY(%s)', (list(vids),))
        return {r[0]: (1 if r[1] else 0) for r in rows}

    def vehicle_detail(self, vid, limit=50):
        rows = self._q(f"SELECT {COLS} FROM vehicle_changes WHERE \"milesId\" = %s ORDER BY id DESC LIMIT %s", (vid, limit))
        keys = ["id", "at", "milesId", "op", "old_status", "new_status", "old_charge", "new_charge", "old_damage", "new_damage", "latitude", "longitude"]
        ch = []
        for r in rows:
            d = dict(zip(keys, r)); d["at"] = d["at"].isoformat(); ch.append(d)
        lk = self._q('SELECT status, latitude, longitude, charge, "damageCount", discounted, updated FROM "MilesVehicleLastKnown" WHERE "milesId" = %s', (vid,))
        last = None
        if lk:
            s, la, lo, c, dc, disc, up = lk[0]
            last = {"status": s, "lat": la, "lon": lo, "charge": c, "damage_count": dc, "discounted": disc, "updated": up.replace(tzinfo=timezone.utc).isoformat()}
        return ch, last
