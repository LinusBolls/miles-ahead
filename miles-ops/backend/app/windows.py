"""Time windows for Berlin restriction and paid-parking strings.
'Mo-Fr 07:00-17:00 Uhr, Sa 09:00-18:00 Uhr' / 'Mo-Fr 9-20 Uhr / Sa 9-18 Uhr' / 'Mo-Sa, 9-22 Uhr' / 'Mo-So' / '' (= always).
Logic follows parse() in miles-ops/analysis/parking_outcomes.py and fee_ledger.py, made tolerant of the odd variants."""
import re
from functools import lru_cache

DAYS = {"Mo": 0, "Di": 1, "Mi": 2, "Do": 3, "Fr": 4, "Sa": 5, "So": 6}
DAY_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
_D = r"(Mo|Di|Mi|Do|Fr|Sa|So)"
SEG = re.compile(_D + r"(?:\s*-\s*" + _D + r")?[\s,/]*(\d{1,2})(?::(\d\d))?\s*-\s*(\d{1,2})(?::(\d\d))?")
DAYS_ONLY = re.compile(_D + r"(?:\s*-\s*" + _D + r")?")


def _days(a, b):
    d0 = DAYS[a]; d1 = DAYS[b] if b else d0
    return frozenset(range(d0, d1 + 1)) if d0 <= d1 else frozenset(list(range(d0, 7)) + list(range(0, d1 + 1)))


@lru_cache(maxsize=4096)
def parse(s):
    """-> None (always), 'unparsed', or tuple of (days, start_h, end_h)."""
    if not isinstance(s, str) or not s.strip():
        return None
    out = []
    for m in SEG.finditer(s):
        a = int(m.group(3)) + int(m.group(4) or 0) / 60
        b = int(m.group(5)) + int(m.group(6) or 0) / 60
        out.append((_days(m.group(1), m.group(2)), a, b))
    if out:
        return tuple(out)
    m = DAYS_ONLY.search(s)
    if m:  # 'Mo-So' without hours -> whole days
        return ((_days(m.group(1), m.group(2)), 0.0, 24.0),)
    return "unparsed"


def active(windows, t_local):
    """t_local: tz-aware datetime in Europe/Berlin."""
    if windows is None:
        return True
    if windows == "unparsed":
        return False
    h = t_local.hour + t_local.minute / 60
    wd = t_local.weekday()
    for days, a, b in windows:
        if b > a:
            if wd in days and a <= h < b:
                return True
        else:  # crosses midnight
            if (wd in days and h >= a) or (((wd - 1) % 7) in days and h < b):
                return True
    return False


def minutes_until_active(windows, t_local, horizon_min=180, step=15):
    """Minutes until the window switches on (0 if active now), None if not within horizon."""
    from datetime import timedelta
    if windows is None or windows == "unparsed":
        return None
    for k in range(0, horizon_min + 1, step):
        if active(windows, t_local + timedelta(minutes=k)):
            return k
    return None


def pretty(s):
    """Short human form: 'Mo-Fr 07:00-17:00 Uhr' -> 'Mo–Fr 07–17'."""
    w = parse(s)
    if w is None:
        return "always"
    if w == "unparsed":
        return s.strip()
    parts = []
    for days, a, b in w:
        ds = sorted(days)
        if ds == list(range(ds[0], ds[-1] + 1)) and len(ds) > 1:
            dtxt = f"{DAY_DE[ds[0]]}–{DAY_DE[ds[-1]]}"
        else:
            dtxt = ",".join(DAY_DE[d] for d in ds)
        f = lambda v: f"{int(v):02d}" + (f":{int(round((v % 1) * 60)):02d}" if v % 1 else "")
        parts.append(dtxt if (a == 0 and b == 24) else f"{dtxt} {f(a)}–{f(b)}")
    return ", ".join(parts)
