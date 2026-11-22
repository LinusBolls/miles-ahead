# "Rescue stranded cars" — deal-supply validation (real replay data)

**Data:** `miles-ops/analysis/rideends_allcities_2024-06.parquet` (one row per customer ride end).
**Scope:** Berlin (`city='BER'`), clean replay window **2024-06-03 .. 2024-06-22 (20 days)**.
**Stranding label (reused from repo `stranding_clean.py` / `build_rideends_allcities.py`):** `idle_h > 12`
— idle_h = hours from a ride ending (status → `DEPLOYED_FOR_RENTAL`) to that vehicle's next status change.
**`charge` field:** 0–100, present for every car; it is the **fuel level for combustion cars and the battery level for EVs**
(299k combustion / 54k electric ride-ends in Berlin). Used as the refuel/charge-credit eligibility signal.
**Centroid:** 52.52, 13.405 (task-requested, Alexanderplatz/S-Bahn-ring centre); distance via (Δlat·111 km, Δlon·68 km).
All numbers below come from `rescue_analysis.py` / `revenue_oppcost.py` run this session; key aggregates in
`rescue_stranded_aggregates.csv`.

---

## DECISION-CRITICAL HEADLINE: do "refuel deals" and "rescue stranded" address the same cars?

**No — they are two largely independent populations.** Only **11.3 % of stranded cars have ≤25 % fuel** (304/day) and
only **3.2 % have ≤15 % fuel** (85/day). Stranded cars' fuel distribution (mean 60.2 %) is **indistinguishable** from
all parked cars (mean 60.9 %). This independently reproduces Carolina's corrected-label result (~3 % at/below 15 %).
**"Pay a user to refuel a car" and "pay a user to rescue a stranded car" are different products targeting different
cars** — do not pitch them as one supply pool. Detail in Q2.

---

## Q1 — How often does stranding happen?

- **Berlin ride-ends in window:** 301,995 (**15,100 / day**) — the denominator.
- **Stranded (idle > 12 h):** **53,616 = 17.75 % of ride-ends = ~2,681 / day.**
- **Cross-check vs MISSION (~2,700/day = 18 %): MATCHES almost exactly.** The repo figure is sound.
- **Daily distribution (20 days):** stranded/day min **2,458**, median **2,698**, max **2,955**; daily rate 14.8 %–20.6 %.
  Very stable day to day (weekends slightly higher rate, higher-volume weekdays slightly lower).

## Q2 — How often is fuel/charge low enough to earn a credit? (the key overlap)

Of the **53,616 stranded** cars:

| Threshold | Stranded cars | % of stranded | per day |
|---|---|---|---|
| charge ≤ 25 % (MISSION "needs a deal") | 6,077 | **11.3 %** | **~304/day** |
| charge < 20 % (Free2Move rule) | 2,797 | 5.2 % | ~140/day |
| **charge ≤ 15 %** (cross-check vs Carolina ~3 %) | **1,699** | **3.2 %** | **~85/day** |
| charge ≤ 10 % | 600 | 1.1 % | ~30/day |

Full charge distribution of stranded cars: 0–10 %: 1.1 % · 11–20 %: 5.5 % · 21–25 %: 4.8 % · 26–30 %: 5.6 %
· 31–50 %: 23.3 % · 51–75 %: 27.1 % · **76–100 %: 32.7 %**. Most stranded cars have **plenty** of fuel/charge.

**Critical honesty finding — stranding and low-fuel are largely DIFFERENT populations.**
- Mean charge: all ride-ends **60.9 %**, stranded **60.2 %**, non-stranded **61.0 %** — essentially identical.
- P(charge ≤ 25 %): base rate across **all** ride-ends **10.4 %**, among stranded **11.3 %** — barely elevated.
  Same at ≤15 %: base **2.5 %**, stranded **3.2 %**. Stranding adds almost nothing to low-fuel likelihood.
- Stranding is driven by **location (low demand)**, not by low fuel. A stranded car is not meaningfully more likely
  to be low-fuel than any other parked car.
- Of the ~304/day low-fuel stranded cars, **294 are combustion (refuel)** and only **10 are EV (charge)**.

## Q3 — How far out are they? (walkability)

Distance from centre (52.52, 13.405):

| Band | Stranded | Stranded + charge ≤ 25 % |
|---|---|---|
| 0–2 km | 3.0 % | 3.6 % |
| 2–5 km (~S-Bahn ring) | 22.4 % | 22.9 % |
| 5–10 km | **46.7 %** | **46.4 %** |
| 10–20 km | 27.9 % | 27.0 % |
| 20 km+ (left city) | 0.1 % | 0.1 % |

- **Stranded median distance 7.33 km** (q25 4.95, q75 10.76, q90 14.38). Low-fuel subset median 7.02 km — same shape.
- **Only ~25 % are within 5 km of centre** (a rough S-Bahn-ring proxy). **~75 % sit in the 5–20 km periphery.**
- 20 km+ outliers are negligible (0.1 %), so the `BER` tag is clean for this window.
- **Walkable + credit-eligible supply: stranded & charge ≤ 25 % & within 5 km of centre = 1,610 cars = ~80/day.**

The stranded population is **predominantly peripheral**, exactly where few potential rescuers live/walk — the opposite
of the "~4 min walk" promise. The small inner-city slice is where the consumer product would actually have takers.

---

## Revenue opportunity cost — what a stranded car costs vs optimal placement

Turnover map over ~400 m grid cells (1,520 cells with ≥30 ride-ends, covering 99 % of ride-ends). "Demand/turnover"
= median dwell (`idle_h`) before a car at that location is re-rented; short dwell = high-turnover "optimal economic area".

**Solid metric (no € assumption) — turnover gap by location:**

| Location | Median dwell before re-rent |
|---|---|
| Optimal (top-decile cells) | **0.8 h** |
| Fleet average cell | 2.0 h |
| Where stranded cars sit | **5.9 h** |

→ Cars in optimal areas turn over roughly **3.6×–4.9× faster** than cars in the cells where stranded cars sit, and
about **2× faster** than the fleet average. A stranded car is unavailable for a **mean 22.3 h (median 18.4 h)** per event.
**This ratio is the defensible number.**

**€ layer — ILLUSTRATIVE, labelled as such.** MILES prices **per-km** (S/M €0.79/km + €1 unlock); this parquet has no
per-ride distance, so there is **no honest per-rental fare in the data**. We therefore express the loss as lost
*productive car-days* × an assumed revenue/car/day band.

- Lost productive car-time (Berlin, per day): **1,123 car-days/day** of idle beyond the 12 h strand threshold
  (conservative: **370 car-days/day** counting only idle beyond 24 h). (cap 72 h to exclude long-dead outliers.)
- Assumed revenue/car/day: **Fraunhofer €3–16/car/day** (UNVERIFIED, older, not free-floating-specific); for context,
  MILES FY24 €227 M / 17,900 cars / 365 = **€34.7/car/day gross** (all cities, incl. subscriptions — an upper anchor).
- **Illustrative lost revenue, Berlin:** 1,123 car-days/day × €3–16 = **~€3.4k–18k/day**; conservative basis
  ~€1.1k–5.9k/day. **Per stranded-car event:** ~0.93 car-days × €3–16 = **~€2.80–€14.90**.

> Note: an earlier naïve proxy (24/dwell as absolute rentals/car/day) implied ~€250k/day — **rejected** as it assumes
> 18–31 rentals/car/day, physically impossible (financials imply ~5 rentals/car/day). The bounded figures above are
> consistent with the Fraunhofer band and are the ones to cite.

---

## VERDICT

**The "rescue stranded + get paid" overlap is small, and the walkable-and-low-fuel slice is smaller still.**

- Stranding is common (~2,681/day) and the location-turnover opportunity cost is **real and defensible** (optimal areas
  re-rent 3.6–4.9× faster than where stranded cars sit). That supports the **relocation/ops** story.
- But **stranding ≠ low fuel**: stranded cars have the same fuel distribution as everything else (mean 60 %); only
  **11.3 % (~304/day)** are credit-eligible at ≤25 %, essentially the base rate. The "rescue + get paid to refuel"
  framing conflates two largely independent problems.
- And the stranded population is **peripheral** (median 7.3 km out, ~75 % beyond 5 km), i.e. far from walk-up rescuers.
- **The intersection the consumer product actually lives on — stranded AND ≤25 % fuel AND within 5 km of centre — is
  ~80 cars/day in all of Berlin.** That is thin for a consumer app, and the honest supply number.

**Implications for the pitch (honest):**
1. "Pay a user to **refuel/charge** a car" is a **low-fuel** targeting problem (MISSION Model 1), **not** a stranding
   problem — keep them separate; don't claim stranded cars are the refuel-deal supply.
2. "Rescue stranded" is better told as **relocation/parking-deal** value (turnover gap, ops console), where the data
   is strong — not as a walk-up consumer refuel deal.
3. If the consumer "needs-a-deal" app is the hero, its real honest supply is the **low-fuel population at ride-end
   (~10 % of all ride-ends, demand-independent)**, surfaced near users — not the peripheral stranded tail.

---

### What I could NOT compute / caveats (flagged)
- **No per-rental fare/distance** in this dataset → the € opportunity cost is illustrative only (assumed €/car-day band).
- **S-Bahn ring is a distance proxy** (<5 km); the parquet has no `inside_sbahn_ring` flag (that field lives only in
  `parks_outcomes_berlin_2024-06.parquet`). Distance quantiles are exact; the ring label is approximate.
- **Turnover = dwell-to-next-status-change**; it conflates re-rental with any status change (e.g. a car taken for
  service), which slightly understates true demand dwell. Ratio across locations is robust to this.
- **idle_h cap 72 h** used for revenue to avoid a handful of 400 h dead-car outliers dominating sums.
- Window is **June replay, labelled**; not live. "Walkability" is proxied by distance-to-centre (population density),
  not by actual user locations (no user data in the set).
