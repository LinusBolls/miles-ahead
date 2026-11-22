"""Euro arithmetic for A (staff relocation) vs B (user reward). Pure arithmetic on numbers printed by
relocations_june.py / rescue_ab_value.py [measured] and public sources [sourced, accessed 2026-11-22]; see
whitepaper/value_model.md section 5 for every source. Usage: python3 miles-ops/analysis/ab_economics.py
"""
REV, FLEET = 226.96e6, 19000          # MILES 2024 annual report: Umsatzerloese; mean of 20,100 / 17,900 year-end fleet
RHO = REV / FLEET / 8760
# contribution margin of an extra rental hour, bounded from the audited P&L
M_LO = (REV - 175.13e6) / REV                     # as if ALL Materialaufwand (incl. leasing, insurance) were variable
M_HI = 1 - (28.38e6 + 5.0e6 + 13.6e6) / REV       # minus fuel/consumables (RHB), payment fees, bad-debt write-downs
print(f"rho = EUR {RHO:.3f}/car-h; margin m in [{M_LO:.3f}, {M_HI:.3f}] -> rho*m in [{RHO*M_LO:.2f}, {RHO*M_HI:.2f}]")

# ---- A: cost per staff relocation ----
DRIVE_H = 36.74 / 60                  # measured median duration
CHAIN = 0.257                         # measured share chained to the next relocation
ACCESS_H = (15 / 60, 30 / 60)         # ASSUMPTION: getting to a non-chained car
HANDLE_H = 4 / 60                     # ASSUMPTION (moves.py HANDLE_MIN)
WAGE = (13.90 * 1.2115, 35.8)         # min wage 2026 x (1 + 21.15 % employer SV)  ...  Destatis labour cost/h, Verkehr+Lagerei 2025
KM = 9.97 * 1.3                        # measured median straight-line km x ASSUMPTION road factor 1.3
CKM = (0.138, 0.182)                   # ADAC Polo: Betriebskosten / + Werkstatt per km (derived at 15,000 km/yr)
FARE = 4.00                            # BVG AB single 2026, non-chained moves only (0 if staff use credits)
h_lo = DRIVE_H + (1 - CHAIN) * ACCESS_H[0] + HANDLE_H
h_hi = DRIVE_H + (1 - CHAIN) * ACCESS_H[1] + HANDLE_H
CA_LO = h_lo * WAGE[0] + KM * CKM[0]
CA_HI = h_hi * WAGE[1] + KM * CKM[1] + (1 - CHAIN) * FARE
print(f"staff hours per relocation {h_lo:.2f}-{h_hi:.2f} h; C_A = EUR {CA_LO:.1f} - {CA_HI:.1f}")
print(f"  floor with perfect chaining (drive time x min wage + km): EUR {DRIVE_H*WAGE[0] + KM*CKM[0]:.1f}")

# ---- hours saved per move (H = 24 h), measured ----
H = {"A as practised (+24.1 h)": 4.19, "A at ride end (hypothetical)": 9.18,
     "B going anyway, 5 min walk": 4.43, "B going anyway, 10 min walk": 5.93,
     "B +<=1 km detour, 5 min walk": 6.46, "B +<=1 km detour, 10 min walk": 7.76,
     "B swap (user would rent anyway), 5 min": 0.52, "B swap, 10 min": 1.00,
     "B dedicated move <=3 km (value-map best cell)": 6.99}
S = 1 - 0.012                         # main.tex: 1.2 % of rescues find the car gone at the >=95 % filter
R = 5.0
print("\nper move: value range (m lo..hi) | cost | net")
for k, h in H.items():
    v_lo, v_hi = h * RHO * M_LO, h * RHO * M_HI
    if k.startswith("A"):
        cost = (CA_LO, CA_HI)
    else:
        v_lo, v_hi = v_lo * S, v_hi * S
        cost = (R * (1 - M_HI), R)    # credit cost: variable cost of an induced ride ... full face value
    print(f"  {k:46s} {h:5.2f} h  value EUR {v_lo:5.2f}-{v_hi:5.2f}  cost EUR {cost[0]:5.2f}-{cost[1]:5.2f}  "
          f"net EUR {v_lo-cost[1]:6.2f} .. {v_hi-cost[0]:6.2f}  R*(mu=0) EUR {v_lo:4.2f}-{v_hi:4.2f}")

print("\nbreak-evens")
print(f"  A pays only if hours saved per move >= C_A/(rho*m): {CA_LO/(RHO*M_HI):.1f} h (cheapest cost, high margin) "
      f"to {CA_HI/(RHO*M_LO):.0f} h; measured 4.19 h; max possible within H=24 is 24-4.93 = 19.07 h")
for k in ("B going anyway, 5 min walk", "B going anyway, 10 min walk", "B +<=1 km detour, 10 min walk"):
    print(f"  {k}: EUR 5 face credit pays at full cost if m >= {R/(H[k]*RHO*S):.2f}")
for walk, car, swap in (("5 min", 4.43, 0.52), ("10 min", 5.93, 1.00)):
    for c in (R, R * (1 - M_HI)):
        need = c / (RHO * M_HI * S)
        q = (need - swap) / (car - swap)
        print(f"  B {walk}: share of incremental (non-swap) rescuers needed at credit cost EUR {c:.2f}, m={M_HI:.2f}: q >= {max(q,0):.2f}")
FLAG, N5, N10 = 1288, 0.562, 0.806
print(f"  B matches A's 186 moves/day if acceptance among flagged cars with a nearby user >= "
      f"{186/(FLAG*N5):.3f} (5 min) / {186/(FLAG*N10):.3f} (10 min)")
print(f"  per move, B beats A whenever credit cost < C_A - rho*m*(h_A - h_B): with h_B >= h_A this is credit < C_A >= EUR {CA_LO:.1f}")
print(f"  Lippoldt 2019 Cologne: 20 bonus minutes at 20-24 ct/min = EUR {20*0.20:.2f}-{20*0.24:.2f} gave a 65 % take rate")
print(f"  annual staff relocation cost at measured volume: 186/day x 365 x C_A = EUR {186*365*CA_LO/1e6:.2f}M - {186*365*CA_HI/1e6:.2f}M")
