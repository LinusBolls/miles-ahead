"""Stranding score with TabPFN (Prior Labs API), GBM fallback.

TabPFN sees RAW features only (no leave-one-out cell rates: they break in-context learning). The whole featurization
lives in `featurize()` so it can be swapped for Carolina's exact recipe in one place.

Live: ride ends are micro-batched (every TABPFN_INTERVAL_S, default 60 s) and scored with
tabpfn_client.TabPFNClassifier() against a fixed 10k-row Berlin context (ride ends June 3-16 2024, label idle > 12 h,
model/tabpfn_context.npz built by build_tabpfn.py). If a call takes longer than TABPFN_TIMEOUT_S (20 s) or fails, the
batch is scored by the GBM in model/ (`fallback`). Replay uses scores precomputed offline (build_tabpfn.py).
The API token comes from the TABPFN_TOKEN env var and is never logged."""
import json, logging, math, os, threading, time
from collections import deque

import numpy as np

log = logging.getLogger("tabpfn")
FEATURES = ["hour", "dow", "charge", "discounted", "damage_count", "size_code", "electric", "model_code",
            "dist_center_km", "x_km", "y_km"]
CATEGORICAL = [FEATURES.index("size_code"), FEATURES.index("model_code")]
CENTER = (52.5163, 13.3777)
SIZES = ["L", "M", "P", "S", "X"]
KM_LAT, KM_LON = 111.2, 67.8   # km per degree at Berlin's latitude


def _num(v):
    try:
        return float(v) if v is not None and v == v else np.nan
    except (TypeError, ValueError):
        return np.nan


def featurize(hour, dow, charge, discounted, damage_count, size, electric, model, lat, lon, vocab):
    """Raw features, one row per ride end. All inputs are equal-length sequences; strings for size/model.
    hour/dow are Berlin local time (dow 0 = Monday)."""
    lat = np.asarray(lat, float); lon = np.asarray(lon, float)
    y_km = (lat - CENTER[0]) * KM_LAT
    x_km = (lon - CENTER[1]) * KM_LON
    sc = np.array([SIZES.index(s) if s in SIZES else np.nan for s in size], float)
    mc = np.array([vocab.get(m, np.nan) if isinstance(m, str) else np.nan for m in model], float)
    return np.column_stack([
        np.asarray(hour, float), np.asarray(dow, float),
        np.array([_num(c) for c in charge], float), np.array([_num(d) for d in discounted], float),
        np.array([_num(d) for d in damage_count], float), sc,
        np.array([float(bool(e)) for e in electric], float), mc,
        np.hypot(x_km, y_km), x_km, y_km,
    ])


def featurize_one(t_local, charge, discounted, damage, size, electric, model, lat, lon, vocab):
    return featurize([t_local.hour], [t_local.weekday()], [charge], [discounted], [damage], [size], [electric], [model],
                     [lat], [lon], vocab)[0]


class Calibration:
    """Plain-words calibration: of ride ends scored in p's bin (out-of-sample), how many really sat > 12 h."""

    def __init__(self, bins):
        self.bins = bins or []   # [{lo, hi, n, rate}]

    def at(self, p):
        for b in self.bins:
            if b["lo"] <= p < b["hi"] or (p >= b["hi"] and b is self.bins[-1]):
                return b
        return None


class StrandScorer:
    """Thresholds, calibration and the live TabPFN client. `threshold(model)` is the Relocate cut-off per model,
    quantile-matched so TabPFN and the GBM fallback flag the same share of ride ends."""

    def __init__(self, model_dir, gbm):
        self.gbm = gbm
        self.meta = json.load(open(os.path.join(model_dir, "tabpfn_meta.json")))
        z = np.load(os.path.join(model_dir, "tabpfn_context.npz"))
        self.X, self.y = z["X"], z["y"]
        self.vocab = self.meta["model_vocab"]
        self.cal = {"TabPFN": Calibration(self.meta["calibration"]["tabpfn"]), "fallback": Calibration(self.meta["calibration"]["gbm"])}
        self.thr = {"TabPFN": float(os.environ.get("TABPFN_THRESHOLD", self.meta["threshold"]["tabpfn"])),
                    "fallback": float(os.environ.get("GBM_MOVE_THRESHOLD", self.meta["threshold"]["gbm"]))}
        self.token = os.environ.get("TABPFN_TOKEN", "")
        self.enabled = bool(self.token) and os.environ.get("TABPFN_LIVE", "1") == "1"
        self.timeout = float(os.environ.get("TABPFN_TIMEOUT_S", "20"))
        self.clf = None
        self.busy = False
        self.lock = threading.Lock()
        self.stats = {"calls": 0, "ok": 0, "fallback_batches": 0, "rows_tabpfn": 0, "rows_fallback": 0,
                      "last_latency_s": None, "last_error": None, "last_call_at": None}
        self.lat_hist = deque(maxlen=200)

    def threshold(self, model):
        return self.thr.get(model, self.thr["fallback"])

    def calibration(self, model, p):
        return self.cal.get(model, self.cal["fallback"]).at(p)

    # ---- live API ----
    def _client(self):
        if self.clf is None:
            import tabpfn_client
            tabpfn_client.set_access_token(self.token)
            clf = tabpfn_client.TabPFNClassifier(random_state=0, categorical_features_indices=CATEGORICAL)
            clf.fit(self.X, self.y)
            self.clf = clf
        return self.clf

    def _predict_blocking(self, X):
        with self.lock:
            return self._client().predict_proba(X)[:, 1]

    def gbm_predict(self, gbm_rows):
        return self.gbm.predict(gbm_rows) if gbm_rows else []

    async def score(self, X, gbm_rows):
        """X: n x len(FEATURES) TabPFN features; gbm_rows: GBM feature dicts for the same ride ends.
        Returns (probabilities, model_name). Never raises."""
        import asyncio
        n = len(gbm_rows)
        if n == 0:
            return [], "TabPFN"
        if self.enabled and not self.busy:
            self.busy = True
            t0 = time.time()
            self.stats["calls"] += 1
            self.stats["last_call_at"] = t0
            fut = asyncio.get_running_loop().run_in_executor(None, self._predict_blocking, np.asarray(X, float))
            try:
                p = await asyncio.wait_for(asyncio.shield(fut), timeout=self.timeout)
                dt = time.time() - t0
                self.stats.update(ok=self.stats["ok"] + 1, last_latency_s=round(dt, 2), last_error=None)
                self.stats["rows_tabpfn"] += n
                self.lat_hist.append(dt)
                return [float(v) for v in p], "TabPFN"
            except asyncio.TimeoutError:
                self.stats["last_error"] = f"timeout > {self.timeout:.0f} s"
                log.warning("tabpfn call timed out after %.0f s, GBM fallback", self.timeout)
            except Exception as ex:
                self.stats["last_error"] = f"{type(ex).__name__}: {str(ex).replace(self.token, '***')[:160]}"
                self.clf = None  # refit (re-upload context) next time
                log.warning("tabpfn call failed: %s", self.stats["last_error"])
            finally:
                if fut.done():
                    self.busy = False
                else:  # slow call: let the thread finish in the background, skip TabPFN until it does
                    def _done(f):
                        self.busy = False
                        if not f.cancelled():
                            f.exception()
                    fut.add_done_callback(_done)
        self.stats["fallback_batches"] += 1
        self.stats["rows_fallback"] += n
        return self.gbm_predict(gbm_rows), "fallback"

    def check_budget(self):
        """Blocking. Disable live TabPFN calls when the account's credits approach the limit (TABPFN_MAX_CREDITS)."""
        if not self.token:
            return None
        try:
            from tabpfn_client.client import ServiceClient
            r = ServiceClient.get_api_usage(self.token)
            used, limit = int(r["current_usage"]), int(r["usage_limit"])
            cap = float(os.environ.get("TABPFN_MAX_CREDITS", str(limit - 500000 if limit > 0 else 1e18)))
            self.stats["credits_used"], self.stats["credits_limit"] = used, limit
            if used >= cap and self.enabled:
                self.enabled = False
                self.stats["last_error"] = f"credit cap reached ({used:,}/{limit:,}): GBM fallback"
                log.warning("tabpfn credit cap reached, switching to fallback")
            return used, limit
        except Exception as ex:
            log.warning("tabpfn usage check failed: %s", type(ex).__name__)
            return None

    def status(self):
        lat = sorted(self.lat_hist)
        s = dict(self.stats)
        rows = s["rows_tabpfn"] + s["rows_fallback"]
        s.update(enabled=self.enabled, timeout_s=self.timeout, busy=self.busy,
                 latency_p50_s=round(lat[len(lat) // 2], 2) if lat else None,
                 latency_p90_s=round(lat[int(len(lat) * 0.9)], 2) if lat else None,
                 fallback_rate=round(s["rows_fallback"] / rows, 3) if rows else None,
                 thresholds=self.thr, context_rows=int(len(self.y)))
        return s
