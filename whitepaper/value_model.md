# What is a stranded car worth moving? A value model, and staff relocation (A) vs user rewards (B)

Status: analysis note for the whitepaper, 22 Nov 2026. Berlin, MILES, June 2024 replay data (historical, labelled as such).
Every number carries a tag: **[measured: file]** (computed this session from our data; script named), **[sourced: URL, accessed 2026-11-22]**, or **[ASSUMPTION]** (then given as a break-even or a range, not a point). `{PLACEHOLDER}` marks TabPFN-regression and destination-model numbers that a parallel run (`miles-ops/analysis/value_tabpfn.py`, results in `miles-ops/analysis/results/`) fills in.

Scripts written for this note (not committed):
- `miles-ops/analysis/relocations_june.py`: MILES staff relocations from the raw status stream → `relocations_berlin_2024-06.parquet`.
- `miles-ops/analysis/rescue_ab_value.py`: value map, realised value of staff relocations, rescue population, user availability, A vs B hours. Output log: `rescue_ab_value.out` in the session scratchpad; rerun the script to reproduce it.
- `miles-ops/analysis/ab_economics.py`: the euro arithmetic in §5 (inputs listed in §5.1).

---

## 0. Verdict (one paragraph)

On our data, the money is in **timing**, and only users can deliver it. MILES' staff relocations (186 a day) start a median **24.1 h** after the last ride [measured: relocations_june.py]. By then **80%** of the cars we flag at ride end have already been rented without help [measured: rescue_ab_value.py]. Each staff move recovers about **4.2 car-hours** (€5.7 revenue at MILES' average €1.36 per car-hour) [measured, H = 24 h]. Even the drive time alone, paid at minimum wage, costs more than that (€10.3 per move; full cost €16–43, §5). Acting at ride end instead recovers about **8.7 h per flagged car** [measured]. No staff team can be at about 1,300 ride ends a day. Users who already start a MILES ride within a 5 or 10 minute walk exist for **56% / 81%** of flagged cars [measured]. Taking the flagged car to where they are going anyway recovers **4.4–5.9 h** per rescue [measured, H = 24 h]. That is comparable to a staff move, at a fraction of the cost, and it is available for 4–6× as many cars (724–1,038 flagged cars a day have a nearby user, against 186 staff moves). The catch, which the A/B test must measure: if that user would have rented another MILES car anyway, the system gains only **0.5–1.0 h** [measured]. The reward then pays for almost nothing. **Stage sentence:** *"MILES already pays drivers to move about 186 cars a day, but a day late, when most of the value is gone. TabPFN flags the car at the moment the ride ends, and the person best placed to move it is a user who is leaving from there anyway."*

---

## 1. Prior art: Florian König's thesis (what it is, what we reuse)

**Source.** F. König, *Forecasting User Behavior to Optimize Fleet Distribution: Investigating the Viability of Predictive Models to Harmonize Supply and Demand in Berlin Carsharing*. BSc Software Engineering thesis, CODE University of Applied Sciences, Berlin, 14 June 2025. The thesis PDF is https://koeni.dev/cities/bsc-thesis.pdf, the PyData Berlin slides are https://koeni.dev/cities/pydata-0925.pdf, and the blog post is https://koeni.dev/blog/analyzing-berlin-carsharing (all accessed 2026-11-22). Florian wrote the scraper that collected our data. His thesis uses a later collection (2025); ours is June 2024.

**Research question (hypothesis, verbatim):** *"I hypothesize that it is feasible to develop predictive models capable of accurately forecasting vehicle demand and user trip destinations within Berlin's carsharing ecosystem. These capabilities could enable targeted incentive mechanisms to encourage users to make trips if they are likely to go to areas experiencing negative supply-demand imbalances."* (§1.1)

**Data.** MILES API, 100 days, 23 Mar to 5 Jul 2025. After cleaning: 1,180,173 trips, 6,486 cars, 877 vans, 1,393,230 reservations, 1,892,705 discount changes, and 42,021 OSM POIs, plus TomTom traffic (20 min, 1.2 km tiles) and weather (hourly, 2.4 km tiles) (Table 3.1). Cleaning removed trips under 1 km or over 12 h (24.7%), holidays (5.3%), and size classes L/XL; 71% of trips remained (§3.2.3).

**Methods.** H3 resolution 8 (about 0.65 km²), 5 time bins × weekday/weekend, and trip starts as observed demand. The spatial statistics are Getis-Ord Gi\*, LASSO, Local Moran's I, OLS vs GAM, and GWR (§4.1). Destinations are modelled as classification over 109 H3-res-7 cells (about 1,320 m edge). The models are a majority baseline, a Bayes upper bound Π_max, multinomial logit, CatBoost and GRU+attention, on a 12-week train / 2-week holdout split (§5.1).

**Findings.**
- POIs explain demand patterns. Multivariate GWR: *"all POI categories combined explain more than 50% of weekday demand deviance (except during the evening bin) and 23-34% on weekends"* (§4.2.4).
- Traffic and weather are irrelevant: they explain *"only 0.7% of the deviation in trip start counts"* (§4.2.5). *"It is not possible to forecast vehicle demand more meaningfully than static patterns using the available data"* (§4.3).
- Destinations are not predictable before the trip. Start cell + hour give Π_max = 11.7%, and all context gives 15.2% top-1. The models reach logit 8.87%, CatBoost 8.69% and GRU 8.97%, against a 6.63% majority baseline (Tables D.1–D.4). *"The theoretical ceiling set by context entropy remains at 15%, a score much too low to base discounts for implicit user relocations on effectively"* (§5.3). With user IDs the bound would be Π\* ≈ 45% (Table D.1); MILES has those IDs and we do not.
- Limitation he names: *"My approach treated demand as the number of trip starts without accounting for unfulfilled demand caused by vehicle unavailability … While the observed fleet's size might render this issue negligible, it could still have influenced my results"* (§4.3).

**Is there a value calculation we can reuse? No.** The thesis contains no utilisation, idle-time, revenue or cost model. The only euro figures are on one PyData slide (p. 4), and both are cited, not computed: *"27min avg. time per relocation in Munich (Weikl, 2016)"* and *"~10€\* cost per relocation, \* based on average driver income"*. The slide also cites *"up to 22.5% increase in revenue while improving fleet balance (Wang et al., 2021)"*. We use the 27 min and €10 only as external cross-checks for our own Berlin measurement (§3). **We could not confirm either figure in the original papers** (search 2026-11-22), so we cite them only "as cited in König (2025)". From his literature review we also take pointers to the incentive evidence. Herrmann et al. 2014, *"85% would choose a more distant car if offered at a 10ct/km discount"*: original not confirmed, do not use as primary. Schiffer et al. 2021, user-based relocation *"can increase fulfilled rental requests by 21% and operator revenue by 10%"*: a simulation, abstract only. Lippoldt et al. 2018/2019, bonus zones led to *"short trips to the border of incentivized areas"*: gaming risk. Lippoldt 2019 is confirmed, with field numbers in §5.3.

**Applies to us.** (i) Demand is spatially structured and stable. That supports a static-plus-time value map and explains why our cell × hour map works (§2). (ii) Short-term signals (weather, traffic) add little, so we leave them out. (iii) Destinations cannot be inferred from anonymous data, so mechanism B must **ask** the user where they are going, or offer a fixed target. It cannot guess. (iv) Unfulfilled demand cannot be seen in scraped data. That is exactly our cannibalisation unknown (§4).

**How we differ.** (1) **Prediction per ride end, not description.** We add TabPFN in three places: P(strand), the distribution of time to next rental, and still-there (§2). (2) **Euro decision model.** We turn predictions into a value difference between two placements and a reward ceiling R\*; the thesis has no economics. (3) **We measure the operator's real counterfactual.** MILES' own relocations (status `IN_RELOCATION_TRIP`) and what happened to those cars afterwards. The thesis did not analyse relocations. Data window (June 2024 vs Mar–Jul 2025) and label (idle > 12 h after a ride end; he removed trips over 12 h) also differ.

---

## 2. The value model

**Unit.** A car of class k (car or van) left at place x at time t. Let I(x, t, k) be the hours until its next customer rental if nobody moves it. I is a random variable with a heavy tail: mean 6.19 h, median 2.21 h, and P(I > 12 h) = 17.2% over all June parks [measured: rescue_ab_value.py].

**Why "hours until the next rental" is the right currency (time-shift argument).** Most stranded cars are not lost rentals. 88% of stranded waits end in a normal booking or ride (main.tex Table 4). A rescue therefore moves the car's next rental earlier by Δ hours. After that rental, the car's future is a fresh draw from the fleet: Berlin trips scatter, with a median of 4.0 km straight-line [measured]. So the whole future is shifted Δ hours earlier, and the fleet gains Δ hours of average car-life. That is worth ρ·m per hour:
- ρ = average revenue per car-hour = €227.0M / 19,000 average cars / 8,760 h = **€1.364** [sourced: MILES Mobility GmbH Jahresabschluss 2024, https://www.lobbyregister.bundestag.de/media/9e/c4/705635/2024_JAP_MILES_Testat_Final_signed_signed.pdf; 19,000 = mean of the 20,100 and 17,900 year-end fleets, per `miles-ops/research/palantir_and_berlin_parking.md`].
- m = contribution margin of an extra rental hour **[ASSUMPTION, bounded in §5]**.

The argument fails exactly where the moved car takes a rental from another car (cannibalisation, κ below).

**Value of a placement over horizon H:**

  V_H(x, t, k) = ρ·m · ( H − E[ min(I(x,t,k), H) ] )

**Rescue value.** The car stands at (x₁, t₁) and is available again at (x₂, t₂ = t₁ + τ). For a staff move, τ is unproductive drive time. For a user who is going there anyway, τ is the wait until the user takes the car; their trip is a normal paid rental.

  ΔV = s · ρ·m · ( E[min(I₁, H) | I₁ > τ_w] − E[min(τ + I₂, H)] ) · (1 − κ)

| Term | Meaning | Estimated by | Status / number |
|---|---|---|---|
| p = P(I₁ > 12 h) | which cars are candidates | **TabPFN classifier**, 10k context | exists; AUC 0.822 served model, 0.846 full features (tabpfn_meta.json; main.tex) |
| distribution of I₁ at (x₁, t₁) | expected idle if left, E[min(I₁,H)], tail P(I₁ > h) | **TabPFN regressor** (predictive distribution, 19 quantiles) | {E1_MAE_TABPFN}, {E1_CRPS_TABPFN} vs GBM 10k {E1_MAE_GBM10K} / GBM full {E1_MAE_GBMFULL}; fallback today: p·h_strand + (1−p)·h_no_strand (moves.py), mean 14.5 h vs realised 15.6 h on flagged cars [measured] |
| distribution of I₂ at (x₂, t₂) | value map: idle at the target | **TabPFN regressor** at target features | {E2_MAE_TABPFN}; baseline today = empirical cell × 3 h × class map, out-of-sample MAE **4.74 h** vs 5.54 h city-by-hour, H = 48 (2.98 vs 3.47 h at H = 12) [measured] |
| x₂ | where the car goes | A: MILES chooses. B: the user's destination, **asked**; prior from a **destination model** | {DEST_TOP1_TABPFN}, {DEST_TOP5}. Florian's ceiling is about 15% top-1 at 1.3 km cells, so a prior, not a decision |
| s = P(car still there when the rescuer arrives) | refund / guarantee | **TabPFN classifier** (still-there); equals 1 − F₁(τ_w) of the regressor | AUC 0.827; 4.7% predicted vs 4.6% observed gone (main.tex §6.4) |
| τ | time until available at x₂ | measured | staff: median 37 min drive [measured]; B: wait until the user starts, 0.25–3 h window |
| κ | share of the moved car's rentals taken from cars already at x₂ | **unknown**: scraped data cannot see unserved demand (Florian §4.3) | proxy: median **2** idle MILES cars already in the 400 m drop-off cell (A); 2–3 (B); only 14–15% of drop-offs have none [measured]. Measure in the A/B test (§6) |
| ρ, m | € per car-hour; margin | annual report; **ASSUMPTION** | ρ = €1.364; m bounded in §5 |

**Decision rule and maximum reward.** If the credit R is paid only for completed rescues, and the guarantee pays R when the car is gone:

  Let ΔV° be the value if the car is there, so ΔV = s·ΔV°. Then
  E[net per accepted offer] = s·(ΔV° − R) − (1 − s)·R = ΔV − R
  **offer iff ΔV − R ≥ μ**, so **R\* = ΔV − μ**, where μ is MILES' required margin per rescue.
  The credit's cost to MILES lies between R·(1 − m) and R (§5.1), so the face value MILES can offer is up to R\*/(1 − m).

**Worked example (the app's car: p = 0.55, moved to Görlitzer Park in the evening, H = 24 h).**
- E[min(I₁, 24)] = **12.08 h**: measured on test cars with p in 0.52–0.58 (n = 1,642). For comparison, the moves.py mixture p·21.44 + (1 − p)·2.88 gives 13.09 h, uncapped.
- E[min(I₂, 24)] at Görlitzer Park, weekday 19–23 h = **4.69 h** (mean, 433 parks). τ = 0.25 h [ASSUMPTION: about 2 km drive]. s = 0.988.
- ΔH = 12.08 − 0.25 − 4.69 = **7.14 h**. That is €9.74 revenue, and **ΔV = €2.19–7.63** at m = 0.23–0.79 (× s). So **R\* = €2.2–7.6** (μ = 0).
- What the app/console computes today: (13.09 − 1.7 median) × €1.364 = **€15.53**, about 2× our estimate, and revenue rather than margin.

**Why a predictive distribution, not a point estimate, is needed:**
1. **Horizon.** E[min(I, H)] ≠ min(E[I], H) because I is heavy-tailed. For cars with p ≈ 0.55, E[min(I, H)] = 8.3 / 12.1 / 14.0 h at H = 12 / 24 / 48 [measured, n = 1,642]. The horizon is a quantile read-out of one distribution, so choosing H needs no refit.
2. **Mean vs median.** Our app's card uses the **median** idle at the target ("~2 h" at Görlitzer Park; median there is 1.8 h). The mean at the same place and hours is 4.8 h (cap 48), with 13% of cars idle > 12 h [measured, 433 parks within 500 m, weekday 19–23 h]. Using medians overstates ΔV by about 3 h, or about €4 of revenue per rescue.
3. **Money-back guarantee.** P(gone) = P(I₁ < τ_w) is the lower tail of the same distribution. The refund cost is (1 − s)·R.
4. **Risk.** The spread of ΔV decides how many offers a fixed budget can safely carry. An operator rule such as "send staff if still idle at 12 h" needs the conditional residual E[I − 12 | I > 12], which a point estimate does not provide.

---

## 3. Measured: MILES' staff relocations (mechanism A as practised)

From the raw status stream, Berlin, 3–22 June 2024 [measured: relocations_june.py, `relocations_berlin_2024-06.parquet`]:

| Quantity | Value |
|---|---|
| Relocations (`IN_RELOCATION_TRIP` runs) | **3,724 = 186/day** (daily min 152, max 239) |
| Duration | median **37 min** (p25 27, p75 47, p90 60). Munich: 27 min (Weikl 2016 as cited on König's slides; not confirmed in the original) |
| Straight-line distance | median **10.0 km** (p25 6.9, p75 13.0) |
| Start delay after last customer ride | median **24.1 h** (p25 17.3, p75 28.5); 83% > 12 h, 51% > 24 h |
| Where from → where to | median 8.7 km → 3.4 km from the centre; 85% end > 1 km further in |
| Time of day | 08–23 h, peak 17–20 h (280–318 starts per hour-slot over 20 days); 00–06 h almost none |
| Wait until the next rental after drop-off | median **1.46 h**, mean 5.72 h (cap 48 h); 0.7% censored |
| Chained (next relocation starts ≤ 1.5 km from drop-off within 60 min) | 25.7% |
| Idle MILES cars already in the 400 m drop-off cell | median 2; 14.9% none; 49.7% ≥ 3 (lower bound: post-ride parks only) |

**Realised value of a staff relocation (natural-experiment comparison).** For each relocated car, we compare it with the cars in the same 1 km cell that had already been idle at least as long, the "stayers". We take their remaining idle within the same horizon H and compare it with the relocated car's wait at its drop-off [measured: rescue_ab_value.py, n = 3,712]:

| Horizon from the move | Stayers' remaining idle | Relocated car's wait | **Hours saved per relocation** |
|---|---|---|---|
| H = 12 h | 6.99 h | 3.72 h | **3.27 h** (median 5.08) |
| H = 24 h | 9.12 h | 4.93 h | **4.19 h** (median 6.67) |
| H = 48 h | 10.29 h | 5.72 h | **4.57 h** (median 7.41) |

By that time the car has already lost a mean **23.3 h** of idle (cap 48) before staff arrive. **Selection bias, stated plainly:** MILES chooses which cars to move, so the stayers are not a randomised control. If MILES moves the worst-placed cars within a cell, we understate the hours saved. If it moves cars that are about to be rented, we overstate them. Matching on cell and elapsed idle removes the two largest confounders. MILES may also relocate for reasons outside rental time: compliance, the service area, morning supply. Our value covers rental time only.

---

## 4. Measured: the rescue population and who could move it (mechanism B)

**Flagged cars** = ride ends with TabPFN p ≥ 0.4556 (top 10%), scored out-of-sample, 17–22 June: **1,288/day**, of which 57.1% really strand. Their expected horizon-capped idle is E[min(I, 24)] = **13.0 h**, against 5.5 h for all cars [measured].

**Timing (same destination quality as staff drop-offs, H = 24 h):**

| Act at | Share still idle | Hours avoidable per flagged car | per car actually moved |
|---|---|---|---|
| ride end + 0.5 h | 94.6% | **8.69 h** | 9.18 h |
| ride end + 24.1 h (staff median) | 19.8% | **1.69 h** | 8.55 h |

Per car moved, the value is similar: waiting 24 h filters out the cars that rent on their own. Acting early, however, recovers **5.1×** more idle hours per day, but needs about 4.8× more moves (1,218 vs 255 a day). No daytime staff team scales to that, which is the case for B.

**Users who are leaving from there anyway.** We look at actual MILES ride starts, 0.25–3 h after the flagged ride end, near the flagged car. Destination = where that trip really ended (198,846 trips with a known destination) [measured]:

| | ≤ 0.4 km (~5 min walk) | ≤ 0.8 km (~10 min walk) |
|---|---|---|
| flagged cars with ≥ 1 such user | **56.2%** | **80.6%** |
| users per such car (median) | 2 | 3 |
| hours saved if the best-destination user takes the flagged car, H = 24 | **4.43 h** | **5.93 h** |
| same, if that user would otherwise have rented another MILES car ("swap") | **0.52 h** | **1.00 h** |
| flagged cars where some user's destination saves ≥ 4 h (H = 48) | 28.1% | 44.7% |
| idle cars already in the destination cell (median; share with none) | 3; 13.5% | 2; 14.1% |

**Dedicated short move (the original "€5 · 4 min walk" card).** The nearest cell with a typical wait ≤ 3 h is a median **4.5 km** from a flagged car. Only 4.6% of flagged cars have one within 1 km, and 29.6% within 3 km [measured]. A dedicated move to the best cell within 1 km saves 4.27 h, and within 3 km 6.99 h (H = 24, including 15 min to move; value-map minimum, so optimistic). This **contradicts the card's premise** that a short walk-and-park captures the 4× demand gap: the gap is mostly 4–10 km away, which is the distance staff actually drive (median 10 km).

---


## 5. A vs B in euros

### 5.1 Inputs (all sourced, measured or bounded)

| Input | Value | Tag |
|---|---|---|
| ρ, revenue per car-hour | €226.96M / 19,000 / 8,760 h = **€1.364** | [sourced: MILES Jahresabschluss 2024 p. 19 (Umsatzerlöse) and p. 11 (fleet 20,100 → 17,900), lobbyregister PDF above] |
| m, margin of an extra rental hour, **low** | (226.96 − 175.13 Materialaufwand)/226.96 = **0.23**: as if all fleet costs, leasing and insurance included, were variable | [derived from sourced P&L, p. 19] |
| m, **high** | 1 − (Roh-/Hilfs-/Betriebsstoffe €28.38M + payment fees €5.0M + bad-debt €13.6M)/226.96 = **0.79** | [derived from sourced P&L, pp. 11–12, 19]. Cross-check: ADAC Polo running cost 13.8 ct/km vs MILES list €0.79/km gives 0.83 |
| Staff wage, low | €13.90/h minimum wage 2026 × 1.2115 employer social contributions = **€16.84/h** | [sourced: bundesregierung.de/breg-de/aktuelles/mindestlohn-steigt-2391010; haufe.de Beitragssätze 2026] |
| Staff wage, high | **€35.8/h** labour cost, Verkehr und Lagerei 2025 | [sourced: destatis.de PD26_148_624, 29 Apr 2026] |
| Drive time per relocation | 37 min median | [measured] |
| Access to the car | 25.7% chained (no access trip). Others: 15–30 min | [measured] / [ASSUMPTION 15–30 min] |
| Handling | 4 min | [ASSUMPTION, as moves.py] |
| Road km | 10.0 km straight-line × 1.3 | [measured] × [ASSUMPTION road factor] |
| Vehicle running cost | 13.8–18.2 ct/km (ADAC VW Polo 1.0, Betriebskosten / + Werkstatt, at 15,000 km/yr) | [sourced: adac.de autokatalog VW Polo VI facelift 351636; derived per km] |
| Transit fare (non-chained) | €4.00 BVG AB single | [sourced: vbb.de neue-fahrpreise-im-vbb-ab-1-januar-2026] |
| Credit R | €5 face. MILES already pays €5 for refuelling below 25% | [sourced: miles-mobility.com/en-de/credit] |
| Credit cost to MILES | between R·(1 − m) = **€1.03** (spent on a ride that would not otherwise happen) and **€5** (spent on a ride that would have happened anyway) | [derived] |
| Still-there s | 98.8% (1.2% gone at the ≥ 95% display filter) | [main.tex §6.4] |

**Cost per staff relocation C_A = €16.4 – €42.9.** That is 0.86–1.05 staff-hours per move plus km and fare [ab_economics.py]. With perfect chaining the floor is €12.1: drive time × minimum wage + km. Cross-checks: crowdsourced relocation in Berlin paid €3–13 per job, at most about 3 jobs an hour, below minimum wage [sourced: berliner-zeitung.de/article/313619, 4 Feb 2023]. König's slide cites "~10€ per relocation" (Munich, driver income). MILES charges customers €100 for a "service trip" by staff, a penalty rather than its cost [sourced: miles-mobility.com/en-de/pricing/fees]. At the measured 186 moves a day, Berlin staff relocation costs about **€1.1–2.9M a year** [derived].

### 5.2 The comparison (H = 24 h, per move)

| Mechanism | Hours saved per move [measured] | Value per move, € (m = 0.23 … 0.79) | Cost per move, € | Net per move, € | Moves possible per day |
|---|---|---|---|---|---|
| **A as practised** (median +24.1 h, MILES picks the cell) | 4.19 | 1.30 … 4.53 | 16.4 … 42.9 | **−41.6 … −11.8** | 186 today (staff-limited); only 19.8% of flagged cars are still idle by then |
| A at ride end (hypothetical) | 9.18 | 2.86 … 9.93 | 16.4 … 42.9 | −40.1 … −6.4 | would need about 1,218 a day, 6.5× today's staff |
| **B, user going anyway, ≤ 5 min walk** | 4.43 | 1.36 … 4.73 | 1.03 … 5.00 | −3.6 … +3.7 | ≤ 724 a day (56.2% of 1,288 flagged) × acceptance |
| **B, user going anyway, ≤ 10 min walk** | 5.93 | 1.82 … 6.34 | 1.03 … 5.00 | −3.2 … +5.3 | ≤ 1,038 a day (80.6%) × acceptance |
| B + ≤ 1 km detour near destination, ≤ 10 min | 7.76 | 2.39 … 8.29 | 1.03 … 5.00 | **−2.6 … +7.3** | as above |
| B, but the user would have rented another MILES car anyway ("swap") | 0.52 – 1.00 | 0.16 … 1.07 | 1.03 … 5.00 | −4.8 … +0.0 | — |
| B, dedicated move to best cell ≤ 3 km (the "€5 · 4 min walk" card) | 6.99 (value-map minimum, optimistic) | 2.15 … 7.47 | 1.03 … 5.00 | −2.9 … +6.4 | user goes out of their way, so acceptance is lower and unknown |

Value = hours × ρ × m (× s for B). Script: `ab_economics.py`. Net ranges combine the worst value with the worst cost and the best with the best.

### 5.3 Break-evens (instead of guesses)

1. **Staff relocation pays on rental time only if a move saves ≥ 15.1 h** (cheapest cost, highest margin), and up to 138 h at the other ends. Measured: **4.19 h**. Within a 24 h horizon the most a move can save is 19.1 h. **No run length rescues A.** Even perfectly chained, one move costs at least €12.1, while the value at m = 0.79 is €4.53. A is uneconomic on rental time as practised. It would need a model that sends staff only to cars whose predicted remaining idle is close to the full day: the TabPFN regressor's conditional tail, {A_TARGETED_HOURS_TABPFN}.
2. **B beats A per move whenever the credit costs MILES less than C_A − ρm·(h_A − h_B).** Because h_B ≥ h_A for every B variant except the swap, this means a credit below **€16.4**. A €5 credit clears that at any acceptance rate. **Acceptance sets B's scale, not its sign.**
3. **€5 credit at full face cost** pays for itself if m ≥ 0.84 (≤ 5 min, going anyway), ≥ 0.63 (≤ 10 min), or ≥ 0.48 (with a ≤ 1 km detour). The audited high bound is 0.79, so a flat €5 works only for the 10-minute/detour variants or when the credit induces extra rides. **Max affordable reward R\*** (μ = 0) = **€1.4–4.7** (5 min), **€1.8–6.3** (10 min), **€2.4–8.3** (10 min + detour). The credit should be **destination-dependent**, priced at R\* for the destination the user enters.
4. **Swap risk.** With a €5 full-cost credit, B (10 min) needs ≥ **75%** of rescuers to be incremental, meaning they would not have rented another MILES car. With a 5-minute radius it never pays. If the credit only costs its variable share (€1.03), ≥ 11% (5 min) or 0% (10 min) is enough. **This share is the number the A/B test must measure.**
5. **Scale.** B matches A's 186 moves a day if ≥ **25.7%** (5 min) or ≥ **17.9%** (10 min) of flagged cars with a nearby user find a taker. Prior art: in Cologne, an FFCS operator's 20-bonus-minute offer (about €4.00–4.80 at the 20–24 ct/min rates in the paper) had a **65% take rate and 46% success**, and cut idle time in the target area by 37% (~12,000 offers) [sourced: Lippoldt, Niels, Bogenberger 2019, Transportation Research Procedia 37:147–154, pp. 151–153, https://athene-forschung.unibw.de/doc/129784/129784.pdf]. Those offers went to customers who were renting anyway, which is the swap case. The take rate transfers; the incremental share does not.

**MILES already has the rails for B.** It pays users €5 for refuelling below 25% and €10 for charging below 30%. It also runs "Bonus Ride" (cars marked "-€") and "Green Rate" (€0.79/km, "save up to 29%") discounts on selected cars [sourced: miles-mobility.com/en-de/credit]. What is missing is *which* car (TabPFN at ride end) and *how much* (R\* from the value difference to the user's destination).

**Hybrid (supported by the numbers):** **B first, at ride end.** Offer a destination-priced credit (≤ R\*) to users who start a ride within 10 minutes' walk of a flagged car; this reaches 80.6% of flagged cars. **A only for the residual tail.** Send staff only to cars still idle where the TabPFN regressor predicts that the remaining idle within the day exceeds C_A/(ρm) (≥ 15 h), plus non-rental reasons such as compliance and the service area. Everything else is left to the market: 80% of flagged cars rent within 24 h without help.

---

## 6. Risks and what the A/B test must add

- **Acceptance (unknown).** The whitepaper's §9 design measures it. Add price arms (€3 / R\* / €8) to fit a(R, walk).
- **Swap / cannibalisation (unknown, decisive).** The current secondary estimand (stranding and idle of the *offered* car) cannot detect it. **Add a cell-level outcome:** total rentals and idle of *all* MILES cars in the target and origin cells, with randomisation by **cell × day** clusters. A rescue that only reorders the queue shows up there as zero.
- **Saturation at the target.** Staff drop-offs and user destinations already have a median of 2–3 idle MILES cars in the same 400 m cell [measured]. κ is the same order for A and B, so it does not change the ranking, only the level.
- **Misuse.** Lippoldt et al. report bonus-zone gaming ("short trips to the border of incentivized areas", via König §2.3.2). Mitigations: pay only for a TabPFN-flagged car, pay on the next customer rental at the target (outcome-based) or cap per user per day (already ~1/day), and set a minimum trip distance.
- **Legal parking.** Staff know the rules; users may leave cars in no-parking zones (tow €225 + admin €70, `moves.py`/`rules.py`). Restrict B targets to legal-parking cells (the ops console's restriction layer).
- **Data honesty.** All of this is June 2024 replay. The value per car-hour is the fleet average (ρ), not Berlin-specific. The staff comparison is observational (selection bias, §3).

---

## 7. What this contradicts in our current pitch and whitepaper

1. **"Value per rescue €17–28" (whitepaper §8, Carolina's scenarios) is 2–4× higher than measured.** €17–28 equals 12.5–20.5 car-hours of revenue at ρ, as if m = 1. Measured at H = 24 h: 4.4–7.8 h per user rescue, which is €6.0–10.6 *revenue* and €1.4–8.3 *contribution* per rescue. The three causes are the horizon cap, mean rather than median wait at the target, and 43% of flagged cars not stranding. So the €130k–1.2M per year in Table `tab:econ` overstates value per rescue and treats revenue as margin. Recompute with h ≈ 4.4–7.8 h and m ∈ [0.23, 0.79].
2. **The "~2 h at Görlitzer Park" card uses the median; the mean is 4.8 h** (`miles-atlas/static/app/api/vehicles.json` says "observed median idle"). `moves.py` correctly uses means.
3. **"€5 · 4 min walk" captures the demand gap only for 4.6% of flagged cars** (a good cell within 1 km). The gap is a median 4.5 km away. The user mechanism that works is "take this car where you're going anyway", not a short dedicated walk-and-park.
4. **Flagged volume and precision:** whitepaper §8 uses 1,490 flagged/day and 58%; the served model on 17–22 June gives **1,288/day and 57.1%** [measured].
5. **"~180 relocations a day, a median 24.6 h late"** is confirmed as **186/day, median 24.1 h** on 3,724 relocations [measured]. Use our number.
6. **Moves.py assumes crew cost €20.** The sourced and measured range is €16.4–42.9, so €20 is at the low end.
7. **€25M fine (MISSION.md).** The audited report says only *"Das Bußgeld wurde auf eine niedrige zweistellige Millionenhöhe festgelegt"* (p. 16). Cite that wording, or a separate source for €25M.
8. **Two citations to avoid as primary:** Herrmann 2014 "85% for 10 ct/km" and Weikl 2016 "27 min per relocation" appear in König's thesis and slides, but we could not confirm them in the originals. Cite them only "as cited in König (2025)".

---

## 8. Open unknowns (to measure, not to model)

| Unknown | Why it matters | How to get it |
|---|---|---|
| Acceptance a(R, walk, destination) | scale of B | A/B price arms |
| Incremental share q (non-swap) | sign of B at a €5 face-cost credit (needs q ≥ 75% at 10 min) | cell × day cluster randomisation, cell-level rentals |
| κ, saturation at the target | level of both A and B | same cell-level outcome |
| m, true marginal margin | € level (0.23–0.79) | MILES internal cost per rental-km |
| Why MILES relocates (non-rental reasons) | A's value beyond rental time | ask MILES ops |
| TabPFN regressor quality | better E₁, E₂, R\*, targeted A | {E1_MAE_TABPFN}, {E2_MAE_TABPFN}, {A_TARGETED_HOURS_TABPFN} from value_tabpfn.py |

---

## 9. Annual scenarios (added after the reframe; script `miles-ops/analysis/ab_scenarios.py`)

Inputs: 1,288 flagged/day [measured], 80.6% reachable within a 10 min walk [measured], h = 5.93–7.76 h per incremental rescue and 1.00 h per swap [measured], m ∈ [0.23, 0.79] [derived], credit = min(€5, R\*) with cost between R(1 − m) and R [derived], acceptance a and incremental share q [ASSUMPTION].

| Scenario | Moves/day | Net per year (q = 75%) | Upper end at q = 50–100% |
|---|---|---|---|
| B, 5% acceptance | 52 | €0–103k | €70k–137k |
| B, 10% acceptance | 104 | €0–207k | €141k–275k |
| B, 20% acceptance | 208 | €0–413k | €281k–550k |
| A, staff relocation as practised | 186 | −€0.8M to −€2.8M (rental time only) | 58k–71k staff-hours/yr |

- The lower bound is €0 because a destination-priced credit never exceeds R\*. A flat €5 credit gives −€270k to +€413k at 20% acceptance.
- The Lippoldt 2019 take rate of 65% is an upper reference only: those offers went to customers who were renting anyway (the swap case).
- Of the 3,341 June staff relocations with a cell estimate, 0.0% have an expected saving of at least the 15.1 h break-even, and 0.8% have at least 10 h.
- This analysis is integrated into `whitepaper/latex/main.tex` §8, which replaces the old economic scenarios.

---

## 10. Weak points and answers (added 22 Nov; script `miles-ops/analysis/weak_points.py`, log in the script's stdout)

Tags as before: [measured: file] = June 2024 Berlin data (`miles-ops/backend/geo/replay_berlin_2024-06.parquet`, `miles-ops/analysis/relocations_berlin_2024-06.parquet`) via `weak_points.py` unless another script is named; [sourced: URL, accessed 2026-11-22]; [ASSUMPTION] with a range. Fares are list tariff (S/M €1 + €0.79/km, vans €2 + €1.29/km [sourced: miles-mobility.com/en-de/pricing]) × straight-line km × road factor 1.3 [ASSUMPTION]. They ignore packages and discounts, so read them as **relative** yields, not revenue.

### W1. "Maybe the idle is intentional: MILES keeps cars at the edges for coverage"

**Steelman.** A free-floating operator sells availability. A car that sits a day in Marzahn may be the reason a customer there trusts the app; the rental that finally ends the wait may be a long, lucrative trip into town; MILES may even send cars outward on purpose. If so, our rescues destroy coverage MILES pays for deliberately.

**(a) Does the rental that ends a stranding pay for the wait? No.** [measured]

| Park location | Idle before next rental | n | Next trip km (median, straight) | Fare (mean) | Idle (mean, cap 48 h) | Fare per idle hour |
|---|---|---|---|---|---|---|
| Inside S-Bahn ring | ≤ 12 h | 127,541 | 3.79 | €5.50 | 2.5 h | €2.23 |
| Inside S-Bahn ring | > 12 h | 11,253 | 3.72 | €5.72 | 17.9 h | **€0.32** |
| Outside ring | ≤ 12 h | 41,625 | 4.78 | €6.89 | 3.6 h | €1.91 |
| Outside ring | > 12 h | 18,427 | 4.62 | €7.07 | 23.2 h | **€0.30** |

- The rental that ends a stranding is **not longer** than a normal rental from the same zone (4.62 vs 4.78 km outside the ring) and earns **€0.17 more** after **19.6 extra idle hours**, which are worth €26.75 of average car-time at ρ = €1.364/h [measured; ρ derived from the annual report]. Inside the ring: +€0.22 for 15.4 extra hours.
- By distance band the pattern holds everywhere: fare per idle hour €0.30–0.41 after a stranding vs €2.04–2.36 otherwise, from 0–5 km to > 15 km.
- Per car-hour of idle + ride, all parks inside the ring yield €1.15, outside €0.65 [measured]. Flagged cars are 89.6% outside the ring vs 31.8% of all parks; the flagged cars that strand earn €0.32 per idle hour, non-flagged parks €1.31.
- **The one exception is BER airport** (hotspot #1). Parks within 1.5 km of Terminal 1: next rental a median **19.6 km**, fare €20.61, yield **€1.53 per car-hour** of idle + ride, above the inside-ring average. 18.5 flagged cars/day (1.4% of flagged), 70% strand [measured]. Airport idle pays for itself; **BER is excluded from rescues.**

**(b) Does MILES send cars outward on purpose? Almost never.** [measured: relocations_berlin_2024-06.parquet]
- Of 3,724 staff relocations: **84.5% inward by > 1 km**, 11.0% lateral (± 1 km), **4.5% outward** (166 in 20 days, 8.3/day).
- Outward moves are short and central: origin a median 3.7 km from the centre, destination 5.5 km; 137 of 166 start within 5 km, only 11 end beyond 10 km.
- No morning supply runs: 06:00–10:00 has the lowest outward share (3.3%, 12 moves in 20 days). Night 00–06 is 10.7% but only 11 moves.
- Zero staff drop-offs within 3 km of BER.
- MILES' revealed preference is to pull cars **in**, a day late (median delay 24.6 h for inward moves).

**(c) Is the flagged car the last one around? Almost never.** [measured; supply = other cars parked after a customer ride or a staff drop-off at that moment, an under-count, so "last car" shares are upper bounds]
- 30 min after ride end, a flagged car has a **median 10 other available MILES cars within 500 m** and 30 within 1 km.
- **1.2% are the last MILES car within 500 m**; 0.5% within 1 km. 92.8% have ≥ 3 others within 500 m; 82.6% have ≥ 5. (Sanity check, random test parks: median 8 others outside the ring, 12 inside.)
- **Customers come and choose another car.** Of the flagged cars that did strand (4,409), **90.9% saw another MILES rental start within 500 m during their first 12 idle hours** (median 4 rentals). The demand is there; the car is surplus.
- The sole-coverage cars sit where nobody rents: the 36 cars alone within 1 km have a median of 0 customer rentals per day starting within 500 m (June 3–16).

| Coverage class (500 m / 1 km) | Share of flagged | Strand rate | Share of flagged idle hours | Another rental within 500 m while idle |
|---|---|---|---|---|
| ≥ 3 other cars within 500 m | 92.8% | 58.0% | 94.0% | 82.7% |
| 1–2 others | 6.0% | 43.5% | 4.7% | 50.1% |
| Last car within 500 m, others within 1 km | 0.7% | 54.5% | 0.7% | 40.0% |
| Last car within 1 km | 0.5% | 55.6% | 0.6% | 2.8% |

**Guard (implemented as a rule, cheap):** no rescue if moving the car leaves no available MILES car within 500 m, and no rescue at BER. Cost: **1.2% + 1.4% of flagged cars**. Pricing coverage is unnecessary at this size.

**(d) Public MILES statements on coverage.** {W1D_SOURCES}

**Verdict W1.** Coverage you would want to keep is at most **~2.6% of flagged cars** (1.2% sole within 500 m, plus 1.4% at BER), and about 1.3% of flagged idle hours outside BER. **At least 94% of flagged idle hours sit next to three or more other idle MILES cars**, in areas where customers rented another car while ours waited. That is oversupply, not coverage. MILES' own staff agree: 84.5% of their moves go inward.

### W2. "Why pay users instead of a minimum-wage employee?"

**Steelman the staff case.** An employee picks the best cell rather than the user's destination; parks legally (MILES charges customers €70 towing admin and €100 for a service trip [sourced: miles-mobility.com/en-de/pricing/fees]); can refuel, clean and check damage in the same visit; is controllable and insured; does not cannibalise a rental MILES would have made anyway; cannot game the bonus. These are real, and they are why staff keep the long tail.

**Answer with data.**
1. **Cost floor.** A perfectly chained staff move at minimum wage costs **≥ €12.1** (drive time × €16.84/h incl. employer contributions + km); a realistic move €16.4–42.9. It saves 4.19 h worth **€1.3–4.5** [measured + derived, `ab_economics.py`]. No chaining closes that gap.
2. **Unproductive time and km.** 74.3% of staff moves are not chained, so each needs an access trip (15–30 min [ASSUMPTION]). Every move drives a median 10.0 km straight (≈ 13 km by road [ASSUMPTION ×1.3]) that earns nothing [measured].
3. **Timing.** Staff start a median **24.1 h** after the last ride; by then 80.2% of flagged cars have already rented without help [measured, `rescue_ab_value.py`]. Acting at ride end instead means **1,219 moves/day** around the clock (1,288 flagged × 94.6% still idle after 30 min).
   - 1,048–1,280 staff-hours a day = **131–160 eight-hour shifts every day** ≈ 232–283 FTE [measured hours per move 0.86–1.05; ASSUMPTION 1,650 productive h per FTE-year].
   - **20.6% of flagged ride ends fall between 22:00 and 06:00**; demand peaks at 193 flagged per hour at 20:00 and falls to 5 at 04:00, so shifts would be badly utilised [measured].
   - Cost **€7.3–19.1M a year** (full cost per move) against recovered rental time worth **€1.3–4.4M** (9.18 h per move × ρm) [derived]. For scale, MILES' whole "operative Dienstleistungen" line (ground operations, all cities) was €35.6M in 2024 [sourced: MILES Jahresabschluss 2024, lobbyregister PDF in §2, via `miles-ops/research/carsharing_business_models.md`]: Berlin ride-end staffing alone would be 20–54% of it.
4. **The rescuer's move is a paid rental.** Rides that start within 800 m of a flagged car 0.25–3 h after its ride end: 33,800 in six days, median 4.19 km, fare **median €5.34, mean €6.39** at list tariff [measured]. The user pays to move the car; a staff move earns €0 and costs €16–43. *Honesty:* that fare is mostly not new revenue, because the user was riding anyway; it is incremental only for the share q of rescuers who would not otherwise have rented (§5.3). The point is that the **transport is free to MILES**, not that the fare is extra.
5. **MILES already pays users.** €5 for refuelling below 25%, €10 for charging below 30%, "Bonus Ride" cars marked "−€" [sourced: miles-mobility.com/en-de/credit]. The rescue credit uses the same rails.
6. **Where staff still win.** The 19.4% of flagged cars no customer passes within 10 minutes' walk; illegal or towing-risk parking; damage, cleaning, refuelling; fraud checks. The hybrid keeps them: staff only where the predicted remaining idle exceeds the break-even (≥ 15.1 h).
7. **Precedents and gig-economy risks.** {W2_PRECEDENTS}

**The "worse version": station an employee at the top stranding hotspots.** [measured; costs derived]
- Flagged ride ends are concentrated but not enough: **the top 20% of the 1,229 400 m cells with a flagged car hold 61.2%**; 168 cells are needed for half. In 1 km cells, the top 20% of 380 hold 65.0%.
- **Top-5 cells hold 4.8% of flagged cars (62/day, 12.4 per cell per day)**; top-20 hold 13.1% (169/day). The top-5 are BER airport (excluded above), two adjacent cells in Marzahn-Hellersdorf (52.546 N 13.587 E; strand 81–88%), one near Rummelsburg (52.495 N 13.487 E) and one at S Zehlendorf (52.434 N 13.258 E).
- Even the best stations see few cars: in the 16:00–22:00 peak, **6 flagged cars per cell per 6-hour shift**.
- Hotspot cars are worth more per move: **10.86 h** avoidable vs 9.18 h for all flagged (H = 24, destination wait 4.93 h) → value **€3.4–11.7**.
- Cost ≈ 1 staff-hour per move (drive + return; capacity-bound at 6 per shift) + km + return fare = **€18.6–42.2** → **net −€38.8 to −€6.9 per move**; break-even 17.2 h.
- **Honest verdict:** stationing beats today's day-late runs per move (10.9 h vs 4.2 h for about the same cost), so it is the right shape *if* MILES insists on staff. But it still loses money on rental time and reaches at most 5% (5 stations) to 13% (20 stations, 20 staff per shift) of flagged cars. It is a complement for the long tail, not an alternative to B.

**Verdict W2.** The staff case is strongest on control and compliance, weakest on money and timing. A staff move costs 3–30 times the rental time it recovers; acting at ride end would take 131–160 shifts a day; the best "station" version reaches 5% of cars. Users win because they are already going there, at ride end, in a ride they pay for. Staff keep the tail.

### Pitch Q&A crib (≤ 3 sentences, one number each)

1. **"Isn't that idle intentional coverage?"** Only 1.2% of the cars we flag are the last MILES car within 500 m, and we never rescue those. The rest stand next to other idle MILES cars that customers rent instead.
2. **"Maybe the edge car earns a long trip back into town?"** No: the rental that ends a stranding is no longer than a normal one from the same area. Per hour of waiting it earns €0.30, a fraction of a normal park. The one exception is the airport, which we exclude.
3. **"Doesn't MILES move cars outward on purpose?"** MILES' own staff move 85% of relocated cars more than a kilometre toward the centre. They agree the edge idle is unwanted; they just get there a day late.
4. **"Why not pay a minimum-wage employee?"** Even perfectly chained at minimum wage, a staff move costs at least €12, more than the rental time it recovers. Our rescuer is already driving that way in a ride they pay for. Staff keep the long tail and compliance work.
5. **"Then let staff act at ride end instead of a day late."** That means about 1,200 moves a day around the clock, including nights. It costs more than the recovered rental time is worth.
6. **"Station someone at the worst hotspots?"** The top five hotspots hold under 5% of flagged cars. It beats today's day-late runs per move but still loses money, so it is a tail tool, not the main lever.
