"""SQLite persistence: decisions (with alert snapshot + outcome) and ledger snapshots (per source/day/zone)."""
import json, sqlite3, threading
from datetime import datetime, timezone


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.lock = threading.Lock()
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, alert_id TEXT, action TEXT,
                note TEXT, operator TEXT, at TEXT, alert_json TEXT, outcome_json TEXT);
            CREATE INDEX IF NOT EXISTS decisions_alert ON decisions(alert_id);
            CREATE INDEX IF NOT EXISTS decisions_at ON decisions(source, at);
            CREATE TABLE IF NOT EXISTS ledger (source TEXT, day TEXT, zone TEXT, eur REAL, updated TEXT, PRIMARY KEY (source, day, zone));
            CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
            """)

    def add_decision(self, source, aid, d, alert):
        with self.lock:
            self.db.execute("INSERT INTO decisions (source, alert_id, action, note, operator, at, alert_json, outcome_json) VALUES (?,?,?,?,?,?,?,?)",
                            (source, aid, d["action"], d["note"], d["operator"], d["at"], json.dumps(alert),
                             json.dumps(alert.get("outcome")) if alert.get("outcome") else None))

    def update_outcome(self, aid, outcome):
        with self.lock:
            self.db.execute("UPDATE decisions SET outcome_json=? WHERE alert_id=?", (json.dumps(outcome), aid))

    def latest_decisions(self, source):
        with self.lock:
            rows = self.db.execute("SELECT alert_id, action, note, operator, at FROM decisions WHERE source=? ORDER BY id", (source,)).fetchall()
        out = {}
        for r in rows:
            d = {"action": r[1], "note": r[2], "operator": r[3], "at": r[4]}
            if r[2] and r[2].startswith("{"):   # moves: {"agent", "run", "seq"} or {"reason"}
                try:
                    d.update(json.loads(r[2]))
                except ValueError:
                    pass
            out[r[0]] = d
        return out

    def count_decisions(self, source, since):
        s = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.lock:
            return self.db.execute("SELECT count(*) FROM decisions WHERE source=? AND at>=?", (source, s)).fetchone()[0]

    def decisions(self, limit=100, source=None):
        q = "SELECT id, source, alert_id, action, note, operator, at, alert_json, outcome_json FROM decisions"
        args = []
        if source:
            q += " WHERE source=?"; args.append(source)
        q += " ORDER BY id DESC LIMIT ?"; args.append(limit)
        with self.lock:
            rows = self.db.execute(q, args).fetchall()
        out = []
        for r in rows:
            a = json.loads(r[7]) if r[7] else {}
            out.append({"id": r[0], "source": r[1], "alert_id": r[2], "action": r[3], "note": r[4], "operator": r[5], "at": r[6],
                        "alert": {k: a.get(k) for k in ("id", "kind", "severity", "title", "vehicle", "zone", "lat", "lon", "created_at", "recommendation", "probability")},
                        "outcome": json.loads(r[8]) if r[8] else None})
        return out

    def delete_decisions(self, source):
        with self.lock:
            return self.db.execute("DELETE FROM decisions WHERE source=?", (source,)).rowcount

    def save_ledger(self, source, day, led):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.lock:
            self.db.executemany("INSERT INTO ledger (source, day, zone, eur, updated) VALUES (?,?,?,?,?) "
                                "ON CONFLICT(source, day, zone) DO UPDATE SET eur=excluded.eur, updated=excluded.updated",
                                [(source, str(day), z, round(e, 4), now) for z, e in led.items()])

    def get(self, k, default=None):
        with self.lock:
            r = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r[0] if r else default

    def put(self, k, v):
        with self.lock:
            self.db.execute("INSERT INTO kv (k, v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))
