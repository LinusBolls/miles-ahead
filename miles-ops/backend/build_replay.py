"""Build the compact replay dataset (Berlin June 2024) for the ops service: geo/replay_berlin_2024-06.parquet.
One row per parking period after a customer ride, with classification, known outcome, vehicle info (masked plate)
and the stranding probability from the exported model (in-sample: the model was fit on June 3-22).
Range: parks starting June 3-22 only. June 24-30 is a scraper collection gap (Berlin ride ends drop from ~15k to ~5k/day,
so missed rides make cars look idle), and the 23rd is dropped so no daytime replay ever runs into it."""
import os as _os
_REPO = _os.environ.get("MILES_REPO", _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../.."))) + "/"  # repo root; raw data goes in data/ (see README)
import json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from app.model import Stranding

A = _REPO + "miles-ops/analysis/"
OUT = os.path.join(os.path.dirname(__file__), "geo", "replay_berlin_2024-06.parquet")
RANGE_UTC = (pd.Timestamp("2024-06-02T22:00"), pd.Timestamp("2024-06-22T22:00"))  # Berlin June 3 00:00 .. June 23 00:00
DAYS = 20


def build():
    p = pd.read_parquet(A + "parks_outcomes_berlin_2024-06.parquet")
    pf = pd.to_datetime(p.parked_from_utc)
    p = p[(pf >= RANGE_UTC[0]) & (pf < RANGE_UTC[1])]
    r = pd.read_parquet(A + "rides_damage_berlin_2024-06.parquet")
    v = pd.read_parquet(_REPO + "data/miles/tables/vehicles.parquet")
    r = r.drop_duplicates(["vehicle_id", "ride_end"])
    d = p.merge(r[["vehicle_id", "ride_end", "ride_start", "prior_damage", "damaged", "end_area", "end_dist", "end_offstreet", "model", "size_class", "electric"]],
                left_on=["vehicle_id", "parked_from_utc"], right_on=["vehicle_id", "ride_end"], how="left")
    d = d.merge(v[["vehicle_id", "license_plate"]], on="vehicle_id", how="left")
    vm = v.set_index("vehicle_id")
    for col in ["model", "size_class", "electric"]:
        d[col] = d[col].fillna(d.vehicle_id.map(vm[col]))


    def mask(pl):
        if not isinstance(pl, str) or len(pl) < 3:
            return "B-MI ••"
        pre, _, num = pl.rpartition(" ")
        return f"{pre or 'B-MI'} ••{num[-2:]}"


    d["plate"] = d.license_plate.map(mask)
    # stranding probability with the live feature pipeline (same code path as the live service)
    s = Stranding(os.path.join(os.path.dirname(__file__), "..", "model"))
    tl = pd.to_datetime(d.parked_from_utc).dt.tz_localize("UTC").dt.tz_convert("Europe/Berlin")
    rows = []
    for i, rr in enumerate(d.itertuples()):
        cls = dict(dist_to_legal_m=rr.dist_to_legal_parking_m if pd.notna(rr.dist_to_legal_parking_m) else None, offstreet=bool(rr.offstreet),
                   area_type=rr.area_type, inside_sbahn_ring=bool(rr.inside_sbahn_ring))
        rows.append(s.features_for(rr.latitude, rr.longitude, tl.iloc[i], rr.ch1, cls, rr.size_class,
                                   bool(rr.electric) if pd.notna(rr.electric) else False, rr.prior_damage if pd.notna(rr.prior_damage) else 0))
    d["p_strand"] = np.round(s.predict(rows), 4)
    keep = ["vehicle_id", "plate", "model", "size_class", "electric", "parked_from_utc", "parked_hours", "latitude", "longitude",
            "inside_sbahn_ring", "dist_to_legal_parking_m", "offstreet", "area_type", "restriction_type", "restriction_reason", "restriction_hours",
            "paid_zone", "paid_zone_fee_eur_h", "paid_zone_hours", "ch1", "prior_damage", "damaged", "next_status", "ops_next", "tow_proxy",
            "moved_m", "active_violation", "violation_h", "p_strand"]
    out = d[keep].sort_values("parked_from_utc").reset_index(drop=True)
    out["electric"] = out.electric.fillna(False).astype(bool)
    out.to_parquet(OUT, index=False, compression="zstd")
    y = out.parked_hours > 12
    sel = out.p_strand >= s.threshold
    print(len(out), "rows ->", OUT, f"{os.path.getsize(OUT)/1e6:.1f} MB")
    print(f"flagged {sel.mean():.1%}, precision {y[sel].mean():.1%} (in-sample), base {y.mean():.1%}")
    ex = (out.parked_hours.clip(upper=72) - 12).clip(lower=0)[y]
    print(f"excess idle per strand: mean {ex.mean():.1f} h; idle car-hours/day beyond 12h {ex.sum()/DAYS:,.0f}; strands/day {y.sum()/DAYS:.0f}")
    print("median parked hours", out.parked_hours.median())


def export_npz(parquet_path, geo_dir):
    """Runtime format without pandas: numeric arrays + small lookup tables."""
    df = pd.read_parquet(parquet_path)
    veh = df.groupby("vehicle_id").agg(plate=("plate", "first"), model=("model", "first"), size_class=("size_class", "first"),
                                       electric=("electric", "first")).reset_index()
    zones = sorted(z for z in df.paid_zone.fillna("").unique() if z)
    zi = {z: i for i, z in enumerate(zones)}
    zmeta = df[df.paid_zone.fillna("") != ""].groupby("paid_zone").agg(fee=("paid_zone_fee_eur_h", "first"), hours=("paid_zone_hours", "first"))
    statuses = sorted(df.next_status.fillna("").unique())
    si = {s: i for i, s in enumerate(statuses)}
    t0 = pd.to_datetime(df.parked_from_utc).values.astype("datetime64[ns]").astype(np.int64)
    np.savez_compressed(os.path.join(geo_dir, "replay_berlin_2024-06.npz"),
        vehicle_id=df.vehicle_id.values.astype(np.int32), t0=t0,
        t1=t0 + (df.parked_hours.values * 3600e9).astype(np.int64),
        lat=df.latitude.values.astype(np.float64), lon=df.longitude.values.astype(np.float64),
        ch1=df.ch1.fillna(-1).values.astype(np.int16), prior_damage=df.prior_damage.fillna(0).astype(int).values.astype(np.int16),
        damaged=df.damaged.fillna(False).astype(bool).values, ops_next=df.ops_next.fillna(False).astype(bool).values,
        tow_proxy=df.tow_proxy.fillna(False).astype(bool).values, p_strand=df.p_strand.fillna(-1).values.astype(np.float32),
        zone=df.paid_zone.fillna("").map(lambda z: zi.get(z, -1)).values.astype(np.int16),
        next_status=df.next_status.fillna("").map(si).values.astype(np.int16),
        parked_hours=df.parked_hours.values.astype(np.float32))
    meta = {"vehicles": {int(r.vehicle_id): [r.plate, r.model, r.size_class, bool(r.electric)] for r in veh.itertuples()},
            "zones": [[z, float(zmeta.loc[z, "fee"]), zmeta.loc[z, "hours"]] for z in zones], "statuses": statuses}
    json.dump(meta, open(os.path.join(geo_dir, "replay_meta.json"), "w"))
    cells = pd.read_parquet(_REPO + "miles-ops/model/cells_berlin.parquet")
    json.dump({r.cell: [float(r.cell_starts_hist), float(r.cell_median_idle_hist)] for r in cells.itertuples()},
              open(os.path.join(geo_dir, "cells_berlin.json"), "w"))
    print("npz written", os.path.getsize(os.path.join(geo_dir, "replay_berlin_2024-06.npz")) / 1e6, "MB")


if __name__ == "__main__":
    if "--export-only" not in sys.argv:
        build()
    export_npz(OUT, os.path.dirname(OUT))
