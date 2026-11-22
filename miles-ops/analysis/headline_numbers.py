"""Recompute the README's headline Berlin numbers from the derived files committed in this repo (no raw data, no API).

  stranding base rate: share of Berlin ride ends (June 3-22 2024) followed by > 12 h idle, and strandings per day
  relocation baseline: staff relocation trips per day and median hours since the last customer ride

Usage: python miles-ops/analysis/headline_numbers.py   (needs pandas + pyarrow; runs in a few seconds)
"""
import os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DAYS = 20  # June 3-22 2024; the status-only record breaks from June 24, so the replay window stops at June 22

d = pd.read_parquet(os.path.join(HERE, "rideends_allcities_2024-06.parquet"))
ber = d[(d.city == "BER") & (d.ride_end_utc >= "2024-06-03") & (d.ride_end_utc < "2024-06-23")]
stranded = ber.idle_h > 12
print(f"Berlin ride ends June 3-22: {len(ber):,}; stranded (idle > 12 h): {stranded.mean():.2%} = {stranded.sum() / DAYS:,.0f}/day")

rel = pd.read_parquet(os.path.join(HERE, "relocations_berlin_2024-06.parquet"))
print(f"staff relocations June 3-22: {len(rel):,} = {len(rel) / DAYS:.0f}/day; "
      f"median start {rel.delay_h.median():.1f} h after the last customer ride")
