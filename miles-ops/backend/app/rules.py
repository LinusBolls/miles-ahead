"""Alert construction: titles, evidence (with sources and base rates), recommendations and EUR estimates.
Numbers: MILES Berlin Jun 2024 analysis (miles-ops/analysis/parking_outcomes.py, parking_offstreet.py, export_model.py)
and miles-ops/research/palantir_and_berlin_parking.md (BKatV fines, Berlin Umsetzung fee, MILES fee schedule, annual report)."""
from .windows import pretty

SRC_MAP = "Berlin Parkraum map (gdi.berlin.de, 2023 scan)"
SRC_ZONES = "Berlin Parkraumbewirtschaftung zones (gdi.berlin.de, 2025-04)"
SRC_OSM = "OpenStreetMap off-street parking (BBBike Berlin extract)"
SRC_HIST = "MILES Berlin Jun 2024"
SRC_BKAT = "BKatV Anlage (Bußgeldkatalog), gesetze-im-internet.de"
SRC_TOW = "service.berlin.de/dienstleistung/324190 (Umsetzung ≤3.5 t)"
SRC_MILES_FEES = "MILES fee schedule (service trip €100, towing admin €70)"
SRC_AR = "MILES annual report 2024 (€227M revenue, ~19k avg cars)"
SRC_MODEL = "Stranding GBM fallback (Berlin Jun 2024)"  # completed from stranding_meta.json by set_validation()
SRC_TABPFN = "TabPFN (Prior Labs API), 10k Berlin ride-end context Jun 3-16 2024"  # completed by set_tabpfn_validation()
TABPFN_VALIDATION = dict(auc=None, precision_top10=None, base_rate=None)

# --- base rates (Berlin, June 2024, parking periods after customer rides) ---
TOW_LEGAL = 0.0141        # n=281,384 legal parks
TOW_INNER_FAR = 0.0317    # n=6,882 inner ring, >20 m, not off-street  (2.3x)
TOW_OUTER_FAR = 0.0470    # n=2,980 outside ring, >20 m, not off-street (3.3x)
IDLE12_OUTER_FAR = 0.485  # share idle >12 h, outer far parks (legal: 19.6%)
TOW_RESTRICTED = {"no_stopping": 0.0127, "loading_zone": 0.0122, "bus_lane": 0.0455, "taxi_stand": 0.0244}
N_RESTRICTED = {"no_stopping": 1416, "loading_zone": 823, "bus_lane": 44, "taxi_stand": 41}

# --- money (research doc B1-B3) ---
EUR_PER_CAR_HOUR = 1.4    # ~€33 per car-day lost revenue (€227M / ~19k cars / 366 d)
TOW_COST = 225 + 100 + 33  # Umsetzung fee + staff retrieval trip (proxy) + one lost car-day
FINE = {"no_stopping": 25, "loading_zone": 25, "taxi_stand": 25, "bus_lane": 55}
FINE_AGGR = {"no_stopping": 40, "loading_zone": 40, "taxi_stand": 40, "bus_lane": 70}  # >1 h (bus lane >3 h / obstruction)
FINE_GEHWEG = 55
EXCESS_IDLE_H = 12.2      # mean idle beyond 12 h for stranded ride ends (Berlin Jun 2024)
VALIDATION = dict(auc=None, precision_top10=None, base_rate=None, threshold=None)  # from stranding_meta.json at startup


def pct(x):
    """0.585 -> '58.5%', 0.17 -> '17%' (one decimal only when it carries information)."""
    return "n/a" if x is None else f"{x * 100:.1f}".rstrip("0").rstrip(".") + "%"


def set_validation(meta):
    """Validation numbers come from model/stranding_meta.json (never hardcoded): AUC, top-10% precision, base rate."""
    global SRC_MODEL
    v = meta.get("validation", {})
    VALIDATION.update(auc=v.get("auc"), precision_top10=v.get("precision_top10pct", v.get("precision_top10")),
                      base_rate=v.get("base_rate"), threshold=meta.get("alert_threshold_top10pct"), train=meta.get("train"))
    train = meta.get("train") or "Berlin Jun 2024"
    SRC_MODEL = f"Stranding GBM fallback ({train.split(' (')[0]}, AUC {VALIDATION['auc']})"


def set_tabpfn_validation(meta):
    """Served-model numbers from model/tabpfn_meta.json: out-of-sample AUC on June 17-22, top-10% precision."""
    global SRC_TABPFN
    m = (meta.get("metrics") or {}).get("tabpfn_clean_split", {})
    TABPFN_VALIDATION.update(auc=m.get("auc"), base_rate=m.get("base_rate"),
                             precision_top10=(meta.get("threshold") or {}).get("precision_tabpfn"))
    SRC_TABPFN = f"TabPFN (Prior Labs API), 10k Berlin ride-end context Jun 3-16 2024, out-of-sample AUC {TABPFN_VALIDATION['auc']}"

LABEL = {"no_stopping": "Halteverbot", "loading_zone": "Ladezone", "bus_lane": "Busspur", "taxi_stand": "Taxistand"}
ALTS = {
    "dispatch": {"action": "dispatch", "label": "Dispatch field agent to re-park"},
    "notify": {"action": "notify_customer", "label": "Ask last customer to re-park"},
    "accept": {"action": "accept", "label": "Accept risk"},
    "relocate": {"action": "relocate", "label": "Relocate to a high-demand cell"},
    "discount": {"action": "discount", "label": "Apply rental discount"},
    "refuel": {"action": "refuel", "label": "Send refuel / charge run"},
    "inspect": {"action": "inspect", "label": "Schedule damage inspection"},
    "ack": {"action": "acknowledge", "label": "Acknowledge"},
}


def _rec(primary, est, alts):
    r = dict(ALTS[primary]); r["est_value_eur"] = round(est) if est is not None else None
    r["alternatives"] = [ALTS[a] for a in alts]
    return r


def ev(label, value, source):
    return {"label": label, "value": value, "source": source}


def restriction_label(cls):
    a = cls["area_type"]
    if a == "no_stopping":
        return "eingeschr. Halteverbot" if cls.get("restriction_type", "").startswith("Eingeschr") else "Halteverbot"
    return LABEL.get(a, a)


def restricted_active(cls, parked_h, switched_on):
    a = cls["area_type"]
    lab = restriction_label(cls)
    hrs = pretty(cls.get("restriction_hours", ""))
    street = cls.get("street") or "unknown street"
    p_tow = TOW_RESTRICTED.get(a, 0.0127)
    fine = FINE_AGGR[a] if parked_h is not None and parked_h > (3 if a == "bus_lane" else 1) else FINE[a]
    est = fine + p_tow * TOW_COST
    title = f"Parked in active {lab} ({hrs}) – {street}"
    if switched_on:
        title = f"{lab} switched on while parked ({hrs}) – {street}"
    e = [
        ev("Restriction", f"{lab}{' (' + cls['restriction_reason'] + ')' if cls.get('restriction_reason') and a == 'no_stopping' else ''}, {hrs}, active now", SRC_MAP),
        ev("Fine exposure", f"€{FINE[a]} (€{FINE_AGGR[a]} {'>3 h' if a == 'bus_lane' else '>1 h'} or obstruction), billed to MILES as keeper", SRC_BKAT),
        ev("Tow exposure", f"Umsetzung up to €225 + ~€100 retrieval trip + ~€33 lost car-day; tow rate in {LABEL[a]} {p_tow:.1%} (n={N_RESTRICTED[a]:,})", f"{SRC_TOW}; {SRC_HIST}"),
        ev("Volume", "83 ride ends/day in Berlin end in an active restriction", f"{SRC_HIST}, n=2,324"),
        ev("Estimate", f"€{fine} fine + {p_tow:.1%} × €{TOW_COST} tow cost ≈ €{est:.0f}", "computed"),
    ]
    if switched_on:
        e.insert(1, ev("Timing", "car was parked legally; restriction window started while it stood here", SRC_MAP))
    if parked_h is not None:
        e.append(ev("Parked", f"{parked_h:.1f} h", "live data"))
    sev = 1
    return dict(kind="restricted_active", severity=sev, title=title, evidence=e, probability=round(p_tow, 4),
                recommendation=_rec("dispatch", est, ["notify", "accept"]))


def restriction_soon(cls, minutes, at_hhmm):
    a = cls["area_type"]
    lab = restriction_label(cls)
    hrs = pretty(cls.get("restriction_hours", ""))
    street = cls.get("street") or "unknown street"
    p_tow = TOW_RESTRICTED.get(a, 0.0127)
    e = [ev("Restriction", f"{lab}, {hrs}: starts {at_hhmm} (in {minutes} min) while the car is parked here", SRC_MAP),
         ev("Fine exposure", f"€{FINE[a]} from {at_hhmm}, billed to MILES as keeper", SRC_BKAT)]
    return dict(kind="restriction_soon", severity=1, title=f"{lab} starts {at_hhmm} – {street}", evidence=e, probability=round(p_tow, 4),
                recommendation=_rec("dispatch", FINE[a] + p_tow * TOW_COST, ["notify", "accept"]))


def far_from_legal(cls):
    inner = cls["area_type"] == "no_legal_parking_nearby"
    d = cls.get("dist_to_legal_m") or 0
    street = cls.get("street") or "unknown street"
    if inner:
        p_tow, n, lift = TOW_INNER_FAR, 6882, TOW_INNER_FAR / TOW_LEGAL
        e = [
            ev("Position", f"{d:.0f} m from the nearest legal street-parking section, inside the S-Bahn ring, not in an off-street car park", f"{SRC_MAP}; {SRC_OSM}"),
            ev("Risk", f"moved without ride 2.3× as often as legal parks ({TOW_INNER_FAR:.1%} vs {TOW_LEGAL:.1%})", f"{SRC_HIST}, n=6,882"),
            ev("Volume", "246 ride ends/day in Berlin park like this", SRC_HIST),
        ]
        est = FINE_GEHWEG + p_tow * TOW_COST
        rec = _rec("notify", est, ["dispatch", "accept"])
        sev = 2
    else:
        p_tow, lift = TOW_OUTER_FAR, TOW_OUTER_FAR / TOW_LEGAL
        idle_cost = (IDLE12_OUTER_FAR - 0.196) * EXCESS_IDLE_H * EUR_PER_CAR_HOUR
        e = [
            ev("Position", f"{d:.0f} m from the nearest street-parking section, outside the S-Bahn ring, not in an off-street car park", f"{SRC_MAP} (outer layer, lower precision); {SRC_OSM}"),
            ev("Risk", f"moved without ride 3.3× as often as legal parks ({TOW_OUTER_FAR:.1%} vs {TOW_LEGAL:.1%}); median idle 11.2 h vs 2.4 h; {IDLE12_OUTER_FAR:.0%} idle >12 h", f"{SRC_HIST}, n=2,980"),
        ]
        est = FINE_GEHWEG + p_tow * TOW_COST + idle_cost
        rec = _rec("relocate", est, ["notify", "accept"])
        sev = 2
    e.append(ev("Estimate", f"€{FINE_GEHWEG} if ticketed on a footway (BKatV 52a) + {p_tow:.1%} × €{TOW_COST} tow cost"
                + ("" if inner else f" + excess idle ≈ €{idle_cost:.0f} at €{EUR_PER_CAR_HOUR}/car-h (assumption)") + f" ≈ €{est:.0f}",
                f"{SRC_BKAT}; {SRC_AR}"))
    title = f"{d:.0f} m from legal parking, not in a car park – {street}" + ("" if inner else " (outer)")
    return dict(kind="far_from_legal", severity=sev, title=title, evidence=e, probability=round(p_tow, 4), recommendation=rec)


def stranding(cls, p, threshold, feats=None, scorer="TabPFN"):
    street = cls.get("street") or cls.get("paid_zone") or "unknown street"
    exp_h = p * EXCESS_IDLE_H
    est = exp_h * EUR_PER_CAR_HOUR
    tab = scorer != "fallback"
    src, val = (SRC_TABPFN, TABPFN_VALIDATION) if tab else (SRC_MODEL, VALIDATION)
    e = [
        ev("Model", f"P(idle >12 h) = {p:.0%}; alert threshold {threshold:.0%} (top 10% of ride ends)"
           + ("" if tab else "; scored by the GBM fallback because the TabPFN call timed out or failed"), src),
        ev("Validation", f"of the top 10% flagged, {pct(val['precision_top10'])} really stranded (base rate {pct(val['base_rate'])}); AUC {val['auc']}", src),
        ev("Context", "~2,700 ride ends/day in Berlin (18%) are followed by >12 h idle; relocated cars rent faster (55% vs 46% within 2 h)", SRC_HIST),
        ev("Estimate", f"{p:.0%} × {EXCESS_IDLE_H} h excess idle × €{EUR_PER_CAR_HOUR}/car-h ≈ €{est:.0f} (assumption: €1.4 revenue per car-hour)", SRC_AR),
    ]
    if feats:
        ch = feats.get("ch1"); chs = f", fuel {ch:.0f}%" if ch is not None and ch == ch else ""
        e.append(ev("Inputs", f"cell demand {feats['cell_starts_hist']:.1f} ride ends/14 d, cell median idle {feats['cell_median_idle_hist']:.1f} h, "
                    f"{feats['dist_center_km']:.1f} km from centre{chs}", SRC_MODEL))
    return dict(kind="stranding", severity=2, title=f"Stranding risk {p:.0%} – idle >12 h likely – {street}", evidence=e,
                probability=round(p, 4), recommendation=_rec("relocate", est, ["discount", "accept"]))


def fleet_ops(city, plate, status):
    return dict(kind="ops", severity=3, title=f"{city}: {plate} entered {status}",
                evidence=[ev("Status", f"{status} (from DEPLOYED / rental)", "MILES API via scraper (vehicle_changes)")],
                probability=None, recommendation=_rec("ack", None, ["inspect"]))


def fleet_low_fuel(city, plate, charge, electric):
    est = 12 * EUR_PER_CAR_HOUR
    what = "charge" if electric else "fuel"
    return dict(kind="low_fuel", severity=3, title=f"{city}: {what} {charge:.0f}% – {plate}",
                evidence=[ev("Level", f"{what} dropped below 20% ({charge:.0f}%)", "MILES API via scraper (vehicle_changes)"),
                          ev("Estimate", f"~12 h unrentable × €{EUR_PER_CAR_HOUR}/car-h ≈ €{est:.0f} (assumption)", SRC_AR)],
                probability=None, recommendation=_rec("refuel", est, ["ack"]))


def fleet_damage(city, plate, n):
    return dict(kind="damage", severity=3, title=f"{city}: new damage report ({n} on record) – {plate}",
                evidence=[ev("Damage", f"damage count rose to {n}", "MILES API via scraper (vehicle_changes)"),
                          ev("Context", "~49 damage reports/day in Berlin; 46% within 15 min of a ride end", f"{SRC_HIST}")],
                probability=None, recommendation=_rec("inspect", 29.5, ["ack"]))
