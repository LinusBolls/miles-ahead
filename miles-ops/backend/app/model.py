"""Stranding model (idle > 12 h after ride end): features exactly as in model/stranding_meta.json."""
import json, math, os, warnings
import numpy as np, joblib


class Stranding:
    def __init__(self, model_dir, cells_json=None):
        self.meta = json.load(open(os.path.join(model_dir, "stranding_meta.json")))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.m = joblib.load(os.path.join(model_dir, "stranding_gbm.joblib"))
        cj = cells_json or os.path.join(model_dir, "cells_berlin.json")
        if os.path.exists(cj):  # exported by build_replay.py (no pandas needed at runtime)
            self.cells = {k: tuple(v) for k, v in json.load(open(cj)).items()}
        else:
            import pandas as pd
            cells = pd.read_parquet(os.path.join(model_dir, "cells_berlin.parquet"))
            self.cells = {r.cell: (float(r.cell_starts_hist), float(r.cell_median_idle_hist)) for r in cells.itertuples()}
        self.default_idle = float(self.meta.get("default_cell_median_idle", 2.434))  # median parked_hours, Berlin Jun 2024
        self.threshold = float(self.meta["alert_threshold_top10pct"])
        self.areas = {a: i for i, a in enumerate(self.meta["areas"])}
        self.sizes = {s: i for i, s in enumerate(self.meta["sizes"])}
        self.clat, self.clon = self.meta["cell_deg"]
        self.center = self.meta["center"]
        self.features = self.meta["features"]

    def cell(self, lat, lon):
        return f"{round(lat / self.clat)}_{round(lon / self.clon)}"

    def features_for(self, lat, lon, t_local, charge, cls, size_class, electric, prior_damage):
        starts, idle = self.cells.get(self.cell(lat, lon), (0.0, self.default_idle))
        f = dict(
            cell_starts_hist=starts, cell_median_idle_hist=idle,
            dist_center_km=math.hypot((lat - self.center[0]) * 111, (lon - self.center[1]) * 68),
            hour=t_local.hour, dow=t_local.weekday(), ch1=charge if charge is not None else np.nan,
            end_dist=cls.get("dist_to_legal_m") if cls.get("dist_to_legal_m") is not None else np.nan,
            end_offstreet=float(cls.get("offstreet", False)),
            area_code=self.areas.get(cls.get("area_type"), np.nan),
            size_code=self.sizes.get(size_class, np.nan),
            electric=float(bool(electric)), prior_damage=prior_damage if prior_damage is not None else np.nan,
            inside_sbahn_ring=float(cls.get("inside_sbahn_ring", False)),
        )
        return f

    def predict(self, rows):
        if not rows:
            return []
        X = np.array([[float(r[f]) if r[f] is not None else np.nan for f in self.features] for r in rows], dtype=float)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # fitted with feature names; numpy input in the same order
            return self.m.predict_proba(X)[:, 1].tolist()
