"""Deterministic BLUF briefing built from engine state (PDB style). Pitch-length: BLUF <= 20 words, each item <= 18 words;
sources and amounts go into the optional per-item `detail`."""
from collections import Counter
from datetime import timedelta

from . import rules
from .engine import BER, iso
from .windows import pretty

SHORT = {"Charlottenburg-Wilmersdorf": "Charlottenburg", "Friedrichshain-Kreuzberg": "Kreuzberg", "Tempelhof-Schöneberg": "Schöneberg",
         "Steglitz-Zehlendorf": "Steglitz", "Treptow-Köpenick": "Treptow", "Marzahn-Hellersdorf": "Marzahn"}


def eur(x):
    if x >= 1e6:
        return f"€{x/1e6:.1f}M"
    if x >= 1e4:
        return f"€{x/1e3:.0f}k"
    if x >= 1e3:
        return f"€{x/1e3:.1f}k"
    return f"€{x:.0f}"


def short_zone(z):
    if not z:
        return "?"
    head, _, num = z.rpartition(" ")
    return f"{SHORT.get(head, head)} {num}" if head else z


def words(s):
    return len([w for w in s.split() if w not in ("–", "-")])


def build(e, city="BER", live_status=None):
    V = rules.VALIDATION
    t = e.engine_now()
    tl = t.astimezone(BER)
    c = e.counters()
    sc = e.scorecard()
    led = e.ledger_view()["zones"]
    open_al = [a for a in e.open_alerts(city, limit=10**9) if not a.get("test")]  # QA test events never shape the briefing
    by_kind = Counter(a["kind"] for a in open_al)

    restr = [pk for pk in e.parked.values() if pk.restricted_now(tl)]
    grp = Counter((pk.zone or pk.cls.get("street") or "?") for pk in restr)
    types = Counter(rules.LABEL.get(pk.cls["area_type"], pk.cls["area_type"]) for pk in restr)
    top_r = grp.most_common(1)[0] if grp else None
    top_name = (short_zone(top_r[0]) if top_r and any(ch.isdigit() for ch in top_r[0][-3:]) else (top_r[0] if top_r else None))

    fee_h, billable = c["fees_eur_per_hour_now"], c.get("cars_billable_now", c["cars_in_paid_zone_now"])
    nr = c["restricted_active_now"]
    if nr:
        tail = f"{nr} in active no-parking zones" + (f", {top_r[1]} in {top_name}" if top_r and top_r[1] > 1 else "") + " – dispatch now."
    elif by_kind.get("stranding"):
        tail = f"{by_kind['stranding']} cars likely to strand – relocate."
    else:
        tail = "no cars in active no-parking zones."
    if fee_h > 0:
        bluf = f"{eur(fee_h)}/h parking fees accruing on {billable:,} cars; {tail}"
    else:
        bluf = f"Outside paid hours, no fees accruing; {tail}"
    if live_status and live_status.get("status") == "stale":
        from datetime import datetime
        last = live_status.get("ber_last_ride_end_at")
        hhmm = datetime.fromisoformat(last).astimezone(BER).strftime("%H:%M") if last else "start"
        bluf = f"Live feed stale since {hhmm} – scraper stopped, figures frozen. Switch to replay."

    items = []
    if restr:
        exp = sum(a["recommendation"]["est_value_eur"] or 0 for a in open_al if a["kind"] == "restricted_active")
        items.append({"text": f"{len(restr)} cars in active no-parking zones – {eur(exp)} fine + tow exposure. Dispatch, start {top_name}.",
                      "filter": {"kind": "restricted_active", "zone": None},
                      "detail": f"{', '.join(f'{n} {k}' for k, n in types.most_common())}. Fines €25 (€40 >1 h) Halteverbot/Ladezone, €55–70 Busspur "
                                f"(BKatV); Umsetzung up to €225 (service.berlin.de) + ~€100 retrieval trip + ~€33 lost car-day. "
                                f"83 ride ends/day end in an active restriction (MILES Berlin Jun 2024, n=2,324)."})
    up = e.upcoming_restrictions(t, 120)
    if up:
        up.sort(key=lambda x: x[1])
        vid, m, pk = up[0]
        when = (tl + timedelta(minutes=m)).strftime("%H:%M")
        n = len(up)
        items.append({"text": f"{n} more {'car' if n == 1 else 'cars'} in restrictions switching on within 2 h – first {when}. Pre-empt.",
                      "filter": {"kind": None, "zone": None, "vehicle_ids": [v for v, _, _ in up][:200]},
                      "detail": f"First: {rules.restriction_label(pk.cls)} {pretty(pk.cls.get('restriction_hours', ''))} at "
                                f"{pk.cls.get('street') or '?'} from {when}. A car parked legally overnight becomes a violation when the window opens."})
    if c["far_from_legal_now"]:
        items.append({"text": f"{c['far_from_legal_now']} cars >20 m from legal parking – moved without ride 2.3× as often.",
                      "filter": {"kind": "far_from_legal", "zone": None},
                      "detail": f"Not in an off-street car park (OSM). Inner ring 3.2% vs 1.4% for legal parks (MILES Berlin Jun 2024, n=6,882); "
                                f"outer 4.7% (n=2,980), median idle 11 h. {by_kind.get('far_from_legal', 0)} open alerts. Ask customers to re-park."})
    st = [a for a in open_al if a["kind"] == "stranding"]
    if st:
        hrs = sum((a["probability"] or 0) * rules.EXCESS_IDLE_H for a in st)
        items.append({"text": f"{len(st)} ride ends likely idle >12 h – ≈{eur(hrs * rules.EUR_PER_CAR_HOUR)} revenue at stake. Relocate top {min(len(st), 10)}.",
                      "filter": {"kind": "stranding", "zone": None},
                      "detail": f"Model top-10% (AUC {V['auc']}): {rules.pct(V['precision_top10'])} of flagged really strand vs {rules.pct(V['base_rate'])} base rate. ≈{hrs:,.0f} expected idle car-hours "
                                f"× €1.4/car-h (assumption: MILES 2024 revenue €227M / ~19k cars). Relocated cars rent faster (55% vs 46% within 2 h)."})
    if led:
        z = led[0]
        items.append({"text": f"{eur(c['fees_eur_today'])} parking fees owed today, {eur(fee_h)}/h now – top {short_zone(z['zone'])} {eur(z['eur_today'])}.",
                      "filter": {"kind": None, "zone": z["zone"]},
                      "detail": f"Independent ledger: each parked car in a paid zone during paid hours × public hourly fee (gdi.berlin.de zones), "
                                f"{sum(1 for r in led if r['eur_today'] > 0)} zones billed today; {z['zone']} has {z['cars_now']} cars now. "
                                f"Know what is owed before anyone else does."})
    s, d = sc["stranding"], sc["decisions"]
    lp = f"{s['live_correct']}/{s['live_checked']} ({s['live_correct']/s['live_checked']:.0%})" if s["live_checked"] else "n/a"
    items.append({"text": f"Closed loop: {d['good']}/{d['outcome_known']} decisions good; stranding model {lp} correct vs {rules.pct(V['precision_top10'])} validated.",
                  "filter": {"kind": None, "zone": None},
                  "detail": f"{c['decisions_today']} decisions today. {s.get('basis', '')}. Validation: {V.get('train') or 'stranding_meta.json'}."})
    items = items[:6]
    return {"generated_at": iso(t) if e.source == "live" else e.disp(t), "bluf": bluf, "items": items, "source": e.source, "city": city}
