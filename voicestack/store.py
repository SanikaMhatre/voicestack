"""VoiceStack booking core.

All booking rules live here, in plain code. No language model ever writes to this
database. Times are naive local (Asia/Kolkata) strings: "YYYY-MM-DDTHH:MM".
Prices are integer paise.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets
import sqlite3
import threading
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
UNIT = 30  # minutes; the smallest bookable block
HOLD_TTL_SECONDS = 120

SCHEMA = """
CREATE TABLE IF NOT EXISTS business(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL,
  approve_code TEXT NOT NULL, open_min INTEGER NOT NULL, close_min INTEGER NOT NULL,
  closed_days TEXT NOT NULL, resources INTEGER NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS service(
  id INTEGER PRIMARY KEY AUTOINCREMENT, business_id TEXT NOT NULL, name TEXT NOT NULL,
  price_paise INTEGER NOT NULL, minutes INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS occupancy(
  business_id TEXT NOT NULL, resource_id INTEGER NOT NULL, start TEXT NOT NULL, ref TEXT NOT NULL,
  PRIMARY KEY(business_id, resource_id, start));
CREATE TABLE IF NOT EXISTS hold(
  id TEXT PRIMARY KEY, business_id TEXT NOT NULL, service_id INTEGER NOT NULL,
  resource_id INTEGER NOT NULL, start TEXT NOT NULL, minutes INTEGER NOT NULL,
  customer TEXT NOT NULL, expires_at TEXT NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS booking(
  id TEXT PRIMARY KEY, business_id TEXT NOT NULL, service_id INTEGER NOT NULL,
  resource_id INTEGER NOT NULL, start TEXT NOT NULL, minutes INTEGER NOT NULL,
  customer TEXT NOT NULL, state TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS idempotency(
  operation TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL, response TEXT NOT NULL,
  PRIMARY KEY(operation, key));
CREATE TABLE IF NOT EXISTS waitlist(
  id TEXT PRIMARY KEY, business_id TEXT NOT NULL, service_id INTEGER NOT NULL, start TEXT NOT NULL,
  customer TEXT NOT NULL, state TEXT NOT NULL, hold_id TEXT, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL,
  business_id TEXT);
"""


def err(code: str, message: str) -> dict:
    return {"ok": False, "error": code, "message": message}


def rupees(paise: int) -> str:
    return f"₹{paise // 100}" if paise % 100 == 0 else f"₹{paise / 100:.2f}"


def hm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


class Store:
    def __init__(self, path: str = ":memory:", clock=None):
        self.clock = clock or (lambda: dt.datetime.now(IST).replace(tzinfo=None))
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        if path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript(SCHEMA)
        cols = [r["name"] for r in self.db.execute("PRAGMA table_info(audit)")]
        if "business_id" not in cols:  # databases created by an earlier version
            self.db.execute("ALTER TABLE audit ADD COLUMN business_id TEXT")

    # ---------- helpers ----------
    def _now(self) -> dt.datetime:
        return self.clock()

    def _audit(self, event: str, business_id: str | None = None, **detail):
        self.db.execute("INSERT INTO audit(ts,event,detail,business_id) VALUES(?,?,?,?)",
                        (self._now().isoformat(timespec="seconds"), event, json.dumps(detail), business_id))

    def _release_expired(self):
        now = self._now().isoformat(timespec="seconds")
        rows = self.db.execute(
            "SELECT id, business_id FROM hold WHERE state='held' AND expires_at < ?", (now,)).fetchall()
        for r in rows:
            self._audit("hold_expired", r["business_id"], hold=r["id"])
            self.db.execute("DELETE FROM occupancy WHERE ref=?", (r["id"],))
            self.db.execute("UPDATE hold SET state='expired' WHERE id=?", (r["id"],))
            self.db.execute("UPDATE waitlist SET state='expired' WHERE hold_id=? AND state='offered'", (r["id"],))

    def _idem(self, op: str, key: str, fp: str):
        row = self.db.execute("SELECT fingerprint,response FROM idempotency WHERE operation=? AND key=?",
                              (op, key)).fetchone()
        if not row:
            return None
        if row["fingerprint"] != fp:
            return err("idempotency_key_reused", "This key was already used for a different request.")
        out = json.loads(row["response"])
        out["replayed"] = True
        return out

    def _idem_save(self, op: str, key: str, fp: str, resp: dict):
        self.db.execute("INSERT INTO idempotency VALUES(?,?,?,?)", (op, key, fp, json.dumps(resp)))

    @staticmethod
    def _fp(*parts) -> str:
        return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()

    # ---------- onboarding (owner approval required) ----------
    def onboard(self, name: str, services: list[dict], open_min: int, close_min: int,
                closed_days: list[int], resources: int = 1, approve_code: str | None = None,
                business_id: str | None = None) -> dict:
        """Two-step. Step 1 creates a DRAFT and returns an approve_code. Step 2 (same
        business_id + approve_code) publishes it. Nothing is bookable until published."""
        with self.lock:
            if business_id and approve_code:
                b = self.db.execute("SELECT * FROM business WHERE id=?", (business_id,)).fetchone()
                if not b:
                    return err("not_found", "Unknown business.")
                if not secrets.compare_digest(b["approve_code"], approve_code):
                    return err("bad_code", "Approval code does not match.")
                self.db.execute("UPDATE business SET status='published' WHERE id=?", (business_id,))
                self._audit("published", business_id)
                return {"ok": True, "status": "published", "business_id": business_id}
            if not name.strip() or not services:
                return err("invalid", "Need a business name and at least one service.")
            if not (0 <= open_min < close_min <= 24 * 60):
                return err("invalid", "Opening hours are invalid.")
            clean = []
            for s in services:
                try:
                    price, mins = int(s["price_paise"]), int(s.get("minutes", UNIT))
                except (KeyError, ValueError, TypeError):
                    return err("invalid", "Each service needs name and price_paise.")
                if price <= 0 or mins <= 0 or mins % UNIT:
                    return err("invalid", f"Service '{s.get('name')}' needs price > 0 and minutes in multiples of {UNIT}.")
                clean.append((str(s["name"]).strip().lower(), price, mins))
            bid = "biz_" + secrets.token_hex(4)
            code = secrets.token_hex(3)
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self.db.execute("INSERT INTO business VALUES(?,?,?,?,?,?,?,?,?)",
                                (bid, name.strip(), "draft", code, open_min, close_min,
                                 json.dumps(sorted(closed_days)), max(1, int(resources)),
                                 self._now().isoformat(timespec="seconds")))
                for n, p, m in clean:
                    self.db.execute("INSERT INTO service(business_id,name,price_paise,minutes) VALUES(?,?,?,?)",
                                    (bid, n, p, m))
                self._audit("draft_created", bid)
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            return {"ok": True, "status": "draft", "business_id": bid, "approve_code": code,
                    "draft": self._describe(bid),
                    "next": "Owner must call onboard_business again with business_id and approve_code to publish."}

    def _describe(self, bid: str) -> dict:
        b = self.db.execute("SELECT * FROM business WHERE id=?", (bid,)).fetchone()
        svcs = self.db.execute("SELECT name,price_paise,minutes FROM service WHERE business_id=?", (bid,)).fetchall()
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        return {"name": b["name"], "hours": f"{hm(b['open_min'])}-{hm(b['close_min'])}",
                "closed": [days[d] for d in json.loads(b["closed_days"])], "chairs": b["resources"],
                "services": [{"name": s["name"], "price": rupees(s["price_paise"]), "minutes": s["minutes"]} for s in svcs]}

    # ---------- discovery ----------
    def find_businesses(self, query: str = "") -> dict:
        with self.lock:
            rows = self.db.execute("SELECT id FROM business WHERE status='published'").fetchall()
            q = query.strip().lower()
            out = []
            for r in rows:
                d = self._describe(r["id"])
                hay = d["name"].lower() + " " + " ".join(s["name"] for s in d["services"])
                if not q or any(w in hay for w in q.split()):
                    out.append({"business_id": r["id"], **d})
            return {"ok": True, "businesses": out}

    def _service(self, bid: str, name: str):
        n = name.strip().lower()
        row = self.db.execute("SELECT * FROM service WHERE business_id=? AND name=?", (bid, n)).fetchone()
        if row:
            return row
        rows = self.db.execute("SELECT * FROM service WHERE business_id=? AND (name LIKE ? OR ? LIKE '%'||name||'%')",
                               (bid, f"%{n}%", n)).fetchall()
        return rows[0] if len(rows) == 1 else None

    def _published(self, bid: str):
        b = self.db.execute("SELECT * FROM business WHERE id=?", (bid,)).fetchone()
        return b if b and b["status"] == "published" else None

    @staticmethod
    def _parse_date(date: str):
        try:
            return dt.date.fromisoformat(date)
        except ValueError:
            return None

    def _free_resource(self, b, start: dt.datetime, minutes: int):
        units = [(start + dt.timedelta(minutes=UNIT * i)).strftime("%Y-%m-%dT%H:%M") for i in range(minutes // UNIT)]
        for res in range(1, b["resources"] + 1):
            q = ",".join("?" * len(units))
            busy = self.db.execute(
                f"SELECT 1 FROM occupancy WHERE business_id=? AND resource_id=? AND start IN ({q})",
                (b["id"], res, *units)).fetchone()
            if not busy:
                return res, units
        return None, units

    def _fits(self, b, start: dt.datetime, minutes: int) -> str | None:
        d = start.date()
        if d.weekday() in json.loads(b["closed_days"]):
            return "The shop is closed that day."
        s = start.hour * 60 + start.minute
        if s < b["open_min"] or s + minutes > b["close_min"] or start.minute % UNIT:
            return "That time is outside opening hours."
        if start <= self._now():
            return "That time has already passed."
        return None

    # ---------- availability ----------
    def get_slots(self, business_id: str, service: str, date: str) -> dict:
        with self.lock:
            b = self._published(business_id)
            if not b:
                return err("not_found", "Unknown or unpublished business.")
            svc = self._service(business_id, service)
            if not svc:
                return err("unknown_service", "No single service matches that name.")
            d = self._parse_date(date)
            if not d:
                return err("invalid_date", "Use YYYY-MM-DD.")
            self._release_expired()
            slots = []
            t = b["open_min"]
            while t + svc["minutes"] <= b["close_min"]:
                start = dt.datetime.combine(d, dt.time(t // 60, t % 60))
                if self._fits(b, start, svc["minutes"]) is None and self._free_resource(b, start, svc["minutes"])[0]:
                    slots.append(hm(t))
                t += UNIT
            return {"ok": True, "business": b["name"], "service": svc["name"], "date": date, "slots": slots}

    # ---------- hold -> confirm ----------
    def hold_slot(self, business_id: str, service: str, date: str, time: str, customer: str) -> dict:
        with self.lock:
            b = self._published(business_id)
            if not b:
                return err("not_found", "Unknown or unpublished business.")
            svc = self._service(business_id, service)
            if not svc:
                return err("unknown_service", "No single service matches that name.")
            if not customer.strip():
                return err("invalid", "Customer name is required.")
            try:
                start = dt.datetime.fromisoformat(f"{date}T{time}")
            except ValueError:
                return err("invalid", "Use date YYYY-MM-DD and time HH:MM.")
            self.db.execute("BEGIN IMMEDIATE")
            try:
                r = self._make_hold(b, svc, start, customer.strip())
                self.db.execute("COMMIT")  # failures return before any write except expiry bookkeeping
                if not r["ok"]:  # written after the rollback so the record survives
                    self._audit("rejected_" + r["error"], business_id, service=svc["name"], start=start.strftime("%Y-%m-%dT%H:%M"))
                return r
            except sqlite3.IntegrityError:
                self.db.execute("ROLLBACK")
                self._audit("rejected_slot_taken", business_id, service=svc["name"], start=start.strftime("%Y-%m-%dT%H:%M"))
                return err("slot_taken", "That slot was just taken. Please choose another time.")
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def _make_hold(self, b, svc, start: dt.datetime, customer: str) -> dict:
        """Must be called inside an open transaction. Returns ok/err dict; caller commits or rolls back."""
        self._release_expired()
        why = self._fits(b, start, svc["minutes"])
        if why:
            return err("unavailable", why)
        res, units = self._free_resource(b, start, svc["minutes"])
        if not res:
            return err("slot_taken", "That slot was just taken. Please choose another time.")
        hid = "hold_" + secrets.token_urlsafe(9)
        exp = self._now() + dt.timedelta(seconds=HOLD_TTL_SECONDS)
        for u in units:  # PRIMARY KEY on occupancy is the double-booking guard
            self.db.execute("INSERT INTO occupancy VALUES(?,?,?,?)", (b["id"], res, u, hid))
        self.db.execute("INSERT INTO hold VALUES(?,?,?,?,?,?,?,?,?)",
                        (hid, b["id"], svc["id"], res, start.strftime("%Y-%m-%dT%H:%M"),
                         svc["minutes"], customer, exp.isoformat(timespec="seconds"), "held"))
        self._audit("held", b["id"], hold=hid, service=svc["name"], start=start.strftime("%Y-%m-%dT%H:%M"))
        return {"ok": True, "hold_id": hid, "expires_in_seconds": HOLD_TTL_SECONDS,
                "read_back": f"{svc['name']} at {b['name']} on {start.strftime('%a %d %b')} at {start.strftime('%H:%M')}, "
                             f"{rupees(svc['price_paise'])}, for {customer}. Confirm?"}

    def confirm_booking(self, hold_id: str, idempotency_key: str) -> dict:
        with self.lock:
            if not idempotency_key.strip():
                return err("invalid", "idempotency_key is required.")
            fp = self._fp(hold_id)
            self.db.execute("BEGIN IMMEDIATE")
            try:
                prev = self._idem("confirm", idempotency_key, fp)
                if prev:
                    self.db.execute("COMMIT")
                    return prev
                self._release_expired()
                h = self.db.execute("SELECT * FROM hold WHERE id=?", (hold_id,)).fetchone()
                if not h:
                    self.db.execute("COMMIT")
                    return err("not_found", "Unknown hold.")
                if h["state"] != "held":
                    self.db.execute("COMMIT")  # only expiry bookkeeping happened; keep it and the audit record
                    self._audit("rejected_confirm_" + h["state"], h["business_id"], hold=hold_id)
                    return err("hold_" + h["state"], "This hold is no longer active. Please search again.")
                bid = "bk_" + secrets.token_urlsafe(9)
                self.db.execute("INSERT INTO booking VALUES(?,?,?,?,?,?,?,?,?)",
                                (bid, h["business_id"], h["service_id"], h["resource_id"], h["start"],
                                 h["minutes"], h["customer"], "confirmed", self._now().isoformat(timespec="seconds")))
                self.db.execute("UPDATE occupancy SET ref=? WHERE ref=?", (bid, hold_id))
                self.db.execute("UPDATE hold SET state='confirmed' WHERE id=?", (hold_id,))
                self.db.execute("UPDATE waitlist SET state='booked' WHERE hold_id=?", (hold_id,))
                resp = {"ok": True, "booking_id": bid, "status": "confirmed", "start": h["start"],
                        "customer": h["customer"]}
                self._idem_save("confirm", idempotency_key, fp, resp)
                self._audit("confirmed", h["business_id"], booking=bid, hold=hold_id)
                self.db.execute("COMMIT")
                return resp
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def cancel_booking(self, booking_id: str) -> dict:
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                b = self.db.execute("SELECT * FROM booking WHERE id=?", (booking_id,)).fetchone()
                if not b:
                    self.db.execute("ROLLBACK")
                    return err("not_found", "Unknown booking.")
                if b["state"] == "cancelled":
                    self.db.execute("ROLLBACK")
                    return {"ok": True, "status": "cancelled", "already_cancelled": True}
                self.db.execute("UPDATE booking SET state='cancelled' WHERE id=?", (booking_id,))
                self.db.execute("DELETE FROM occupancy WHERE ref=?", (booking_id,))
                self._audit("cancelled", b["business_id"], booking=booking_id)
                offered = self._offer_to_waitlist(b["business_id"], b["start"])
                self.db.execute("COMMIT")
                return {"ok": True, "status": "cancelled", "already_cancelled": False, "waitlist_offered": offered}
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    # ---------- waitlist ----------
    def _offer_to_waitlist(self, business_id: str, start_iso: str) -> bool:
        """Inside a transaction: offer the freed time to the longest-waiting customer who now fits."""
        b = self._published(business_id)
        rows = self.db.execute(
            "SELECT * FROM waitlist WHERE business_id=? AND state='waiting' AND start=? ORDER BY created, rowid",
            (business_id, start_iso)).fetchall()
        for w in rows:
            svc = self.db.execute("SELECT * FROM service WHERE id=?", (w["service_id"],)).fetchone()
            r = self._make_hold(b, svc, dt.datetime.fromisoformat(w["start"]), w["customer"])
            if r["ok"]:
                self.db.execute("UPDATE waitlist SET state='offered', hold_id=? WHERE id=?", (r["hold_id"], w["id"]))
                self._audit("waitlist_offer", business_id, waitlist=w["id"], hold=r["hold_id"])
                return True
        return False

    def join_waitlist(self, business_id: str, service: str, date: str, time: str, customer: str) -> dict:
        with self.lock:
            b = self._published(business_id)
            if not b:
                return err("not_found", "Unknown or unpublished business.")
            svc = self._service(business_id, service)
            if not svc:
                return err("unknown_service", "No single service matches that name.")
            if not customer.strip():
                return err("invalid", "Customer name is required.")
            try:
                start = dt.datetime.fromisoformat(f"{date}T{time}")
            except ValueError:
                return err("invalid", "Use date YYYY-MM-DD and time HH:MM.")
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self._release_expired()
                why = self._fits(b, start, svc["minutes"])
                if why:
                    self.db.execute("ROLLBACK")
                    return err("unavailable", why)
                if self._free_resource(b, start, svc["minutes"])[0]:
                    self.db.execute("ROLLBACK")
                    return err("slot_free", "That slot is free right now. Book it directly.")
                dup = self.db.execute("SELECT id FROM waitlist WHERE business_id=? AND service_id=? AND start=? AND customer=? "
                                      "AND state IN ('waiting','offered')",
                                      (business_id, svc["id"], start.strftime("%Y-%m-%dT%H:%M"), customer.strip())).fetchone()
                if dup:
                    self.db.execute("ROLLBACK")
                    return {"ok": True, "waitlist_id": dup["id"], "state": "waiting", "already_waiting": True}
                wid = "wl_" + secrets.token_urlsafe(7)
                self.db.execute("INSERT INTO waitlist VALUES(?,?,?,?,?,?,?,?)",
                                (wid, business_id, svc["id"], start.strftime("%Y-%m-%dT%H:%M"), customer.strip(),
                                 "waiting", None, self._now().isoformat(timespec="seconds")))
                self._audit("waitlist_joined", business_id, waitlist=wid)
                self.db.execute("COMMIT")
                return {"ok": True, "waitlist_id": wid, "state": "waiting",
                        "message": "You are on the waitlist. If this slot is cancelled you get a 2-minute offer."}
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def check_waitlist(self, waitlist_id: str) -> dict:
        with self.lock:
            self._release_expired()
            w = self.db.execute("SELECT * FROM waitlist WHERE id=?", (waitlist_id,)).fetchone()
            if not w:
                return err("not_found", "Unknown waitlist entry.")
            out = {"ok": True, "waitlist_id": waitlist_id, "state": w["state"]}
            if w["state"] == "offered":
                svc = self.db.execute("SELECT * FROM service WHERE id=?", (w["service_id"],)).fetchone()
                b = self.db.execute("SELECT * FROM business WHERE id=?", (w["business_id"],)).fetchone()
                st = dt.datetime.fromisoformat(w["start"])
                out.update(hold_id=w["hold_id"], expires_in_seconds=HOLD_TTL_SECONDS,
                           read_back=f"A slot opened up: {svc['name']} at {b['name']} on {st.strftime('%a %d %b')} at "
                                     f"{st.strftime('%H:%M')}, {rupees(svc['price_paise'])}, for {w['customer']}. Confirm?")
            return out

    # ---------- owner dashboard (read-only) ----------
    def day_view(self, business_id: str, date: str) -> dict:
        with self.lock:
            b = self.db.execute("SELECT * FROM business WHERE id=?", (business_id,)).fetchone()
            if not b:
                return err("not_found", "Unknown business.")
            self._release_expired()
            like = date + "T%"
            items = []
            for r in self.db.execute(
                "SELECT bk.id,bk.start,bk.minutes,bk.customer,bk.state,bk.resource_id,s.name svc,s.price_paise FROM booking bk "
                "JOIN service s ON s.id=bk.service_id WHERE bk.business_id=? AND bk.start LIKE ?", (business_id, like)):
                items.append({"kind": "booking", "id": r["id"], "start": r["start"][11:], "minutes": r["minutes"],
                              "customer": r["customer"], "service": r["svc"], "state": r["state"], "chair": r["resource_id"],
                              "price_paise": r["price_paise"]})
            now = self._now()
            for r in self.db.execute(
                "SELECT h.id,h.start,h.minutes,h.customer,h.resource_id,h.expires_at,s.name svc,s.price_paise FROM hold h "
                "JOIN service s ON s.id=h.service_id WHERE h.business_id=? AND h.state='held' AND h.start LIKE ?",
                (business_id, like)):
                left = int((dt.datetime.fromisoformat(r["expires_at"]) - now).total_seconds())
                items.append({"kind": "hold", "id": r["id"], "start": r["start"][11:], "minutes": r["minutes"],
                              "customer": r["customer"], "service": r["svc"], "state": "held", "chair": r["resource_id"],
                              "expires_in": max(0, left), "price_paise": r["price_paise"]})
            waiting = self.db.execute("SELECT COUNT(*) FROM waitlist WHERE business_id=? AND state='waiting' AND start LIKE ?",
                                      (business_id, like)).fetchone()[0]
            closed = dt.date.fromisoformat(date).weekday() in json.loads(b["closed_days"])
            return {"ok": True, "business": b["name"], "date": date, "open_min": b["open_min"], "close_min": b["close_min"],
                    "chairs": b["resources"], "closed": closed, "items": items, "waiting": waiting}

    def audit_list(self, business_id: str, limit: int = 50) -> dict:
        """Business-scoped change log, newest first. Includes rejected attempts (conflicts, expired holds)."""
        with self.lock:
            if not self.db.execute("SELECT 1 FROM business WHERE id=?", (business_id,)).fetchone():
                return err("not_found", "Unknown business.")
            rows = self.db.execute("SELECT ts,event,detail FROM audit WHERE business_id=? ORDER BY id DESC LIMIT ?",
                                   (business_id, max(1, min(int(limit), 200)))).fetchall()
            return {"ok": True, "events": [{"ts": r["ts"], "event": r["event"], **json.loads(r["detail"])} for r in rows]}
