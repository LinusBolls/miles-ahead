"""MILES Parking Control API (served under /ops/api by nginx; this app sees paths without the prefix)."""
import asyncio, json, logging, os, time
from datetime import datetime
from typing import List, Optional

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

import numpy as np

from . import briefing as briefing_mod, rules
from .engine import BER, UTC, Engine, iso
from .moves import Demand, Moves
from .strand_tabpfn import StrandScorer, featurize_one
from .geo import BerlinGeo
from .live import LiveSource
from .model import Stranding
from .qa import KINDS as QA_KINDS, QA
from .replay import ReplayEngine, ReplaySource
from .store import Store

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ops")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO_DIR = os.environ.get("GEO_DIR", os.path.join(BASE, "geo"))
MODEL_DIR = os.environ.get("MODEL_DIR", os.path.join(BASE, "model"))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE, "data"))
DSN = os.environ.get("OPS_DB_DSN", "")
SPEED = float(os.environ.get("REPLAY_SPEED", "5"))
STRANDING_CAP = int(os.environ.get("STRANDING_CAP", "25"))  # inbox shows the top-N stranding alerts by risk; the rest are summarized
ENABLE_LIVE = os.environ.get("ENABLE_LIVE", "1") == "1"
TABPFN_INTERVAL_S = float(os.environ.get("TABPFN_INTERVAL_S", "60"))          # live micro-batch
TABPFN_NIGHT_INTERVAL_S = float(os.environ.get("TABPFN_NIGHT_INTERVAL_S", "300"))  # 00:00-06:00 Berlin: few ride ends, save credits

app = FastAPI(title="MILES Parking Control API", docs_url="/docs", openapi_url="/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])
S = {}


@app.on_event("startup")
async def startup():
    t = time.time()
    os.makedirs(DATA_DIR, exist_ok=True)
    geo = BerlinGeo(os.path.join(GEO_DIR, "berlin_geo.pkl.gz"))
    geo.classify([52.52], [13.40])  # build trees now
    model = Stranding(MODEL_DIR, os.path.join(GEO_DIR, "cells_berlin.json"))
    rules.set_validation(model.meta)
    store = Store(os.path.join(DATA_DIR, "ops.db"))
    scorer = StrandScorer(MODEL_DIR, model, os.path.join(DATA_DIR, "tabpfn_counters.json"))
    rules.set_tabpfn_validation(scorer.meta)
    demand = Demand(os.path.join(GEO_DIR, "demand_berlin.npz"), geo)
    live = Engine("live", geo, model, store, "a_")
    rep = ReplayEngine("replay", geo, model, store, "r_")
    for e in (live, rep):
        e.scorer = scorer
        e.moves = Moves(e, demand, scorer)
    if scorer.enabled:
        live.strand_queue = []
    S.update(geo=geo, model=model, store=store, scorer=scorer, demand=demand, engines={"live": live, "replay": rep})
    S["replay"] = ReplaySource(rep, os.path.join(GEO_DIR, "replay_berlin_2024-06.npz"), SPEED)
    S["live"] = LiveSource(live, DSN) if (ENABLE_LIVE and DSN) else None
    S["qa"] = QA(geo, model, S["replay"].c["lat"], S["replay"].c["lon"])
    S["tasks"] = [asyncio.create_task(S["replay"].run())]
    if S["live"]:
        S["tasks"].append(asyncio.create_task(S["live"].run()))
        S["tasks"].append(asyncio.create_task(strand_loop()))
    S["tasks"].append(asyncio.create_task(counters_loop()))
    log.info("startup done in %.1fs (live=%s)", time.time() - t, bool(S["live"]))


async def strand_loop():
    """Live: every TABPFN_INTERVAL_S, score the queued ride ends in one TabPFN call (GBM fallback if > 20 s or error)."""
    e, sc, lv = S["engines"]["live"], S["scorer"], S["live"]
    last_budget = 0
    while True:
        hour = datetime.now(BER).hour
        await asyncio.sleep(TABPFN_NIGHT_INTERVAL_S if hour < 6 else TABPFN_INTERVAL_S)
        try:
            if time.time() - last_budget > 1800:
                last_budget = time.time()
                await asyncio.to_thread(sc.check_budget)
            q = e.strand_queue
            if not q:
                continue
            batch = [b for b in q if (e.parked.get(b[1]) is not None and e.parked[b[1]].pid == b[0])]
            q.clear()
            if not batch:
                continue
            try:
                disc = await asyncio.to_thread(lv.discounted, {b[1] for b in batch})
            except Exception:
                disc = {}
            X, gbm_rows = [], []
            for pid, vid, t, lat, lon, cls in batch:
                v = e.vehicle(vid); tl = t.astimezone(BER)
                X.append(featurize_one(tl, v.get("charge"), disc.get(vid, 0), v.get("damage") or 0, v.get("size_class"), v.get("electric"),
                                       v.get("model"), lat, lon, sc.vocab))
                gbm_rows.append(e.model.features_for(lat, lon, tl, v.get("charge"), cls, v.get("size_class"), v.get("electric"), v.get("damage") or 0))
            p, name = await sc.score(np.array(X), gbm_rows)
            made = 0
            for (pid, vid, t, lat, lon, cls), pi in zip(batch, p):
                pk = e.parked.get(vid)
                if pk is None or pk.pid != pid:
                    continue
                made += 1 if e.strand_alert(pid, vid, t, lat, lon, cls, float(pi), name, discounted=bool(disc.get(vid))) else 0
            log.info("strand batch: %d ride ends, %s, %d moves, %.2fs", len(batch), name, made, sc.stats["last_latency_s"] or -1)
        except Exception:
            log.exception("strand loop")


def model_block():
    sc = S["scorer"]; m = sc.meta
    return {"tabpfn": m["metrics"]["tabpfn_clean_split"], "carolina": m["metrics_carolina"], "threshold": m["threshold"],
            "context": m["context"], "value": m["value"], "live": sc.status(), "gbm": {"auc": rules.VALIDATION.get("auc"), "train": rules.VALIDATION.get("train")},
            "replay_precompute_calls": m["replay_precompute"]["n_calls"], "features": m["features"]}


def moves_snapshot(e):
    snap = dict(e.moves.build())
    snap["clock"] = e.counters() if e.source == "replay" else {"clock_speed": 1.0}
    return snap


@app.on_event("shutdown")
async def shutdown():
    if S.get("scorer"):
        S["scorer"].save_counters()


async def counters_loop():
    n = 0
    while True:
        await asyncio.sleep(3)
        n += 1
        if n % 20 == 0:   # every minute
            await asyncio.to_thread(S["scorer"].save_counters)
        for name, e in S["engines"].items():
            try:
                e.expire_tests(600)
            except Exception:
                log.exception("expire_tests")
            if e.subs:
                try:
                    c = e.counters(); c["open_alerts"] = len(e.open_alerts("BER", limit=10**9))
                    e.publish("counters", c, None)
                    e.publish("moves", moves_snapshot(e), None)
                except Exception:
                    log.exception("counters")


def eng(source):
    if source not in ("live", "replay"):
        raise HTTPException(400, "source must be live or replay")
    return S["engines"][source]


def freshness(e):
    if e.source == "replay":
        return 0
    lv = S.get("live")
    t = (lv.ber_last_change_at or lv.last_change_at) if lv else None
    if t:
        return round((datetime.now(UTC) - t).total_seconds(), 1)
    return None


@app.get("/health")
async def health():
    lv = S.get("live")
    h = lv.health() if lv else {"ok": False, "db_lag_s": None, "last_change_at": None, "error": "live source disabled"}
    rp = S["replay"].status()
    h = dict(h, **S["engines"]["live"].telemetry())
    rp = dict(rp, **S["engines"]["replay"].telemetry())
    return {"ok": bool(h["ok"]) or rp["ok"], "db_lag_s": h["db_lag_s"], "last_change_at": h["last_change_at"],
            "live": h, "replay": rp, "tabpfn": S["scorer"].status(), "now": iso(datetime.now(UTC)),
            "excluded_airport": {"live": h.get("excluded_airport", 0), "live_today": h.get("excluded_airport_today", 0),
                                 "replay": rp.get("excluded_airport", 0),
                                 "rule": "ride ends inside the BER airport box 52.355-52.372 N, 13.495-13.535 E never become stranding alerts or moves"}}


def cap_stranding(al, cap):
    """Inbox balance: keep every non-stranding alert, plus the top-`cap` open stranding alerts by model probability
    (decided and QA test alerts always stay). Act-now first, then newest."""
    st = [a for a in al if a["kind"] == "stranding" and not a.get("decision") and not a.get("test")]
    st.sort(key=lambda a: -(a.get("probability") or 0))
    keep = {a["id"] for a in st[:cap]}
    shown = [a for a in al if a["kind"] != "stranding" or a["id"] in keep or a.get("decision") or a.get("test")]
    shown.sort(key=lambda a: 0 if a["kind"] == "restricted_active" else 1)  # stable: newest-first within each group
    summ = {"open": len(st), "shown": min(cap, len(st)), "hidden": max(0, len(st) - cap),
            "min_p_shown": round(st[min(cap, len(st)) - 1].get("probability") or 0, 3) if st else None}
    return shown, summ


@app.get("/state")
async def state(source: str = "live", city: str = "BER", limit: int = 300, stranding_cap: int = STRANDING_CAP):
    e = eng(source)
    al = e.open_alerts(city, limit=10**9)
    counters = e.counters()
    counters["open_alerts"] = len(al)  # same snapshot as the list; alerts[] is capped at `limit`
    shown, summ = cap_stranding(al, max(0, min(stranding_cap, 1000)))
    out = {"now": iso(datetime.now(UTC)), "source": source, "city": city, "counters": counters,
           "alerts": shown[:min(limit, 1000)], "alerts_total": len(al), "stranding_summary": summ,
           "scorecard": e.scorecard(), "ledger": e.ledger_view(), "data_freshness_s": freshness(e)}
    if source == "replay":
        out["replay"] = S["replay"].status()
    else:
        lv = S.get("live")
        out["live"] = dict(ready=bool(lv and lv.rebuilt), error=lv.error if lv else "disabled",
                           **(lv.status() if lv else {"status": "error", "message": "live source disabled"}))
    return out


@app.get("/briefing")
async def briefing(source: str = "live", city: str = "BER"):
    lv = S.get("live")
    return briefing_mod.build(eng(source), city, lv.status() if (source == "live" and lv) else None)


@app.get("/stream")
async def stream(request: Request, source: str = "live", city: str = "BER", lite: int = 0):
    e = eng(source)
    q = asyncio.Queue(maxsize=600)  # ~2 min of replay at 20x; beyond that the client gets `reset` and reloads
    e.subs.add(q)

    def fmt(ev, data):
        return f"event: {ev}\ndata: {json.dumps(data, separators=(',', ':'), default=str)}\n\n"

    async def gen():
        try:
            yield "retry: 3000\n\n"
            yield fmt("counters", e.counters())
            if lite:
                yield fmt("moves", moves_snapshot(e))
            last_ping = time.time()
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev, data, c = await asyncio.wait_for(q.get(), timeout=1.0)
                    if lite and ev in ("alert", "decision"):
                        continue   # moves UI: snapshots come as `moves` events
                    if ev in ("alert", "decision") and city not in (None, "ALL") and c != city:
                        continue
                    yield fmt(ev, data)
                except asyncio.TimeoutError:
                    pass
                if time.time() - last_ping >= 15:
                    yield fmt("ping", {"now": iso(datetime.now(UTC))}); last_ping = time.time()
        finally:
            e.subs.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


def _engine_for_alert(aid):
    return S["engines"]["replay"] if aid.startswith("r") else S["engines"]["live"]


@app.get("/moves")
async def moves(source: str = "live"):
    """Tonight's moves: open runs (ranked), assigned runs, today's tally, model info."""
    e = eng(source)
    out = moves_snapshot(e)
    out["model"] = model_block()
    if source == "replay":
        out["replay"] = S["replay"].status()
    else:
        lv = S.get("live")
        out["live"] = dict(ready=bool(lv and lv.rebuilt), **(lv.status() if lv else {"status": "error", "message": "live source disabled"}))
    return out


@app.get("/moves/{move_id}")
async def move_detail(move_id: str):
    e = _engine_for_alert(move_id)
    d = e.moves.detail(move_id)
    if d is None:
        raise HTTPException(404, f"move {move_id} not found")
    return d


def _push_moves(e):
    e.moves.cache = (0, None)
    if e.subs:
        e.publish("moves", moves_snapshot(e), None)


@app.post("/moves/assign")
async def moves_assign(body: dict = Body(...)):
    """Assign a run (ordered move ids) to a named field agent. Body {move_ids, agent, operator, run_id?}."""
    ids, agent = body.get("move_ids") or [], (body.get("agent") or "").strip()[:40]
    if not ids or not agent:
        raise HTTPException(400, "move_ids and agent required")
    op = (body.get("operator") or "ops")[:40]
    run = body.get("run_id") or f"run:{ids[0]}"
    out, missing = [], []
    e = _engine_for_alert(ids[0])
    for seq, mid in enumerate(ids):
        x = {"agent": agent, "run": run, "seq": seq}
        if body.get("channel") in ("crew", "rider"):
            x["channel"] = body["channel"]
        a = _engine_for_alert(mid).decide(mid, "assign", json.dumps(x), op, extra=x)
        (out.append(mid) if a else missing.append(mid))
    _push_moves(e)
    return {"assigned": out, "missing": missing, "agent": agent, "run_id": run}


@app.post("/moves/skip")
async def moves_skip(body: dict = Body(...)):
    """Skip one move with a reason. Body {move_id, reason, operator}."""
    mid, reason = body.get("move_id"), (body.get("reason") or "").strip()[:120]
    if not mid or not reason:
        raise HTTPException(400, "move_id and reason required")
    e = _engine_for_alert(mid)
    a = e.decide(mid, "skip", json.dumps({"reason": reason}), (body.get("operator") or "ops")[:40], extra={"reason": reason})
    if a is None:
        raise HTTPException(404, f"move {mid} not found")
    _push_moves(e)
    return {"skipped": mid, "reason": reason}


@app.post("/decision")
async def decision(body: dict = Body(...)):
    action = body.get("action")
    if not action:
        raise HTTPException(400, "action required")
    note, operator = body.get("note", ""), body.get("operator", "ops")
    ids = body.get("alert_ids")
    if ids:
        out, missing = [], []
        for aid in ids:
            a = _engine_for_alert(aid).decide(aid, action, note, operator)
            (out.append(Engine.public(a)) if a else missing.append(aid))
        return {"alerts": out, "missing": missing}
    aid = body.get("alert_id")
    if not aid:
        raise HTTPException(400, "alert_id or alert_ids required")
    a = _engine_for_alert(aid).decide(aid, action, note, operator)
    if a is None:
        raise HTTPException(404, f"alert {aid} not found")
    return Engine.public(a)


@app.get("/decisions")
async def decisions(limit: int = 100, source: Optional[str] = None):
    rows = S["store"].decisions(min(limit, 1000), source)
    for r in rows:  # attach the freshest outcome from memory
        e = _engine_for_alert(r["alert_id"])
        a = e.alerts.get(r["alert_id"])
        if a is not None:
            r["outcome"] = a.get("outcome"); r["status"] = a["status"]
    return {"decisions": rows}


@app.get("/vehicle/{miles_id}")
async def vehicle(miles_id: int, source: str = "live"):
    e = eng(source)
    v = e.vehicles.get(miles_id)
    if v is None and source == "replay":
        raise HTTPException(404, "vehicle not in replay")
    past = sorted([Engine.public(a) for a in e.alerts.values() if a["vehicle"]["miles_id"] == miles_id], key=lambda a: a["created_at"], reverse=True)
    pk = e.parked.get(miles_id)
    parked = None
    if pk:
        parked = {"since": e.disp(pk.t0), "lat": pk.lat, "lon": pk.lon, "kind": pk.kind, "classification": pk.cls}
    out = {"vehicle": e.vpub(miles_id) if v else {"miles_id": miles_id}, "parked": parked, "alerts": past[:50]}
    if source == "live":
        lv = S.get("live")
        try:
            ch, last = await asyncio.to_thread(lv.vehicle_detail, miles_id) if lv else ([], None)
        except Exception as ex:
            ch, last = [], None
            out["error"] = type(ex).__name__
        out["changes"], out["last_known"] = ch, last
    else:
        out["changes"] = S["replay"].vehicle_detail(miles_id)
    return out


@app.get("/cars")
async def cars(source: str = "live"):
    """Parked Berlin cars for the map layer: [miles_id, lat, lon, billing 0/1]. Updated live by SSE park/depart."""
    e = eng(source)
    return JSONResponse({"source": source, "cars": e.cars_snapshot()}, headers={"Cache-Control": "no-cache"})


@app.get("/geo/paid_zones.geojson")
def paid_zones():
    return FileResponse(os.path.join(GEO_DIR, "paid_zones.geojson"), media_type="application/geo+json",
                        headers={"Cache-Control": "public, max-age=3600"})


@app.get("/replay/status")
async def replay_status():
    return S["replay"].status()


@app.post("/replay/restart")
async def replay_restart(speed: Optional[float] = None):
    S["replay"].pending_restart = speed or S["replay"].speed
    for _ in range(50):
        await asyncio.sleep(0.2)
        if S["replay"].pending_restart is None:
            break
    return S["replay"].status()


@app.post("/replay/speed")
async def replay_speed(speed: float):
    """Change replay speed without restarting (sim clock stays continuous). Shared by every viewer of the replay."""
    rp = S["replay"]
    rp.set_speed(speed)
    e = S["engines"]["replay"]
    c = e.counters(); c["open_alerts"] = len(e.open_alerts("BER", limit=10**9))
    e.publish("counters", c, None)
    return rp.status()


@app.post("/qa/inject")
async def qa_inject(kind: str, source: str = "replay"):
    """Inject one fake alert ("test": true) into a source's stream. Defaults to replay; live only when source=live is
    given explicitly. Rate-limited (token bucket, 12 burst, 1 per 3 s)."""
    kind = {"relocate": "stranding", "clear_active": "restricted_active", "clear_soon": "restriction_soon", "clear_far": "far_from_legal"}.get(kind, kind)
    if kind == "fleet":
        kind = S["qa"].rng.choice(["low_fuel", "ops", "damage"])
    if kind not in QA_KINDS:
        raise HTTPException(400, f"kind must be one of {', '.join(QA_KINDS)} or fleet")
    e = eng(source)
    ok, wait = S["qa"].allow()
    if not ok:
        raise HTTPException(429, f"rate limited: retry in {wait} s", headers={"Retry-After": str(int(wait) + 1)})
    await asyncio.to_thread(S["qa"].ensure_pool)
    a = S["qa"].inject(e, kind)
    if a is None:
        raise HTTPException(500, "inject failed")
    _push_moves(e)
    return Engine.public(a)


@app.post("/qa/clear")
async def qa_clear(source: str = "replay"):
    """Resolve every open QA test alert in a source (they fade out in the UI)."""
    n = eng(source).expire_tests(all_=True)
    _push_moves(eng(source))
    return {"cleared": n}


@app.post("/admin/reset-replay")
async def admin_reset_replay(request: Request, restart: bool = True):
    """Clear all replay decisions (SQLite + memory) and restart the replay. Localhost only: requests through nginx carry
    X-Forwarded-For and are refused."""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1") or request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip"):
        raise HTTPException(403, "localhost only")
    n = S["store"].delete_decisions("replay")
    e = S["engines"]["replay"]
    e.decisions = {}
    for a in e.alerts.values():
        if a.get("decision"):
            a["decision"] = None
            if a["status"] == "decided":
                a["status"] = "open"
    if restart:
        S["replay"].pending_restart = S["replay"].speed
        for _ in range(50):
            await asyncio.sleep(0.2)
            if S["replay"].pending_restart is None:
                break
    return {"deleted_decisions": n, "replay": S["replay"].status()}
