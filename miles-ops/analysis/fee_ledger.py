"""Independent parking-fee ledger: car-hours MILES cars stood in Berlin paid zones during paid hours (June 2024), x public hourly fee."""
import re, numpy as np, pandas as pd
d = pd.read_parquet("parks_outcomes_berlin_2024-06.parquet")
D = {"Mo":0,"Di":1,"Mi":2,"Do":3,"Fr":4,"Sa":5,"So":6}
def parse(s):
    out=[]
    for part in re.split(r"[/,;]", s or ""):
        m=re.search(r"(Mo|Di|Mi|Do|Fr|Sa|So)(?:\s*-\s*(Mo|Di|Mi|Do|Fr|Sa|So))?\s*(\d{1,2})\s*-\s*(\d{1,2})", part)
        if m:
            a=D[m[1]]; b=D[m[2]] if m[2] else a
            out.append((set(range(a,b+1)), int(m[3]), int(m[4])))
    return out
cache={}
def billable(t, h, s):
    w = cache.setdefault(s, parse(s))
    if not w: return 0.0
    # hourly-resolution walk, capped at 72 h
    n = int(np.ceil(min(h,72)*4)); ts = t + pd.to_timedelta(np.arange(n)*15, unit="min")
    hrs = ts.hour.values; wd = ts.weekday.values
    ok = np.zeros(n, bool)
    for days,a,b in w: ok |= np.isin(wd, list(days)) & (hrs>=a) & (hrs<b)
    return ok.sum()*0.25
z = d[d.paid_zone_fee_eur_h.notna() & (d.paid_zone_hours.fillna("")!="")].copy()
z["t"] = pd.to_datetime(z.parked_from_utc).dt.tz_localize("UTC").dt.tz_convert("Europe/Berlin")
z["bill_h"] = [billable(t,h,s) for t,h,s in zip(z.t, z.parked_hours, z.paid_zone_hours)]
z["fee_eur"] = z.bill_h * z.paid_zone_fee_eur_h
days = 28
print(f"parks in paid zones: {len(z):,} of {len(d):,} ({len(z)/len(d):.0%})")
print(f"billable car-hours/day {z.bill_h.sum()/days:,.0f}; fee at public rates: EUR {z.fee_eur.sum()/days:,.0f}/day = EUR {z.fee_eur.sum()/days*365/1e6:.1f}M/year")
print("note: only parking after customer rides that we observed (dense data); ops-held time excluded")
print(z.groupby("paid_zone_fee_eur_h").agg(parks=("fee_eur","size"), car_h_day=("bill_h", lambda s: s.sum()/days), eur_day=("fee_eur", lambda s: s.sum()/days)).round(0))
top = z.groupby("paid_zone").fee_eur.sum().sort_values(ascending=False).head(8)/days
print("\ntop zones EUR/day:"); print(top.round(0))
z[["vehicle_id","parked_from_utc","paid_zone","paid_zone_fee_eur_h","bill_h","fee_eur"]].to_parquet("fee_ledger_berlin_2024-06.parquet", index=False)
