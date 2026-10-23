import datetime as dt
import threading

import pytest

from voicestack.parser import parse_onboarding, parse_request
from voicestack.store import Store

NOW = dt.datetime(2026, 10, 22, 9, 0)  # Thursday
TOMORROW = "2026-10-23"  # Friday


@pytest.fixture
def s():
    return Store(":memory:", clock=lambda: NOW)


def published(s, resources=1, text="haircut 300, beard 150 60min, open 10-8, closed monday"):
    p = parse_onboarding(text)
    d = s.onboard("Raj Salon", p["services"], p["open_min"], p["close_min"], p["closed_days"], resources)
    assert d["status"] == "draft"
    s.onboard("", [], 0, 1, [], approve_code=d["approve_code"], business_id=d["business_id"])
    return d["business_id"]


def test_draft_is_not_bookable_until_owner_approves(s):
    p = parse_onboarding("haircut 300, open 10-8")
    d = s.onboard("X", p["services"], p["open_min"], p["close_min"], p["closed_days"])
    assert s.find_businesses()["businesses"] == []
    assert s.get_slots(d["business_id"], "haircut", TOMORROW)["error"] == "not_found"
    bad = s.onboard("", [], 0, 1, [], approve_code="wrong", business_id=d["business_id"])
    assert bad["error"] == "bad_code"


def test_onboarding_parser():
    p = parse_onboarding("haircut 300, beard 150 60min, open 10-8, closed monday")
    assert [(x["name"], x["price_paise"], x["minutes"]) for x in p["services"]] == [("haircut", 30000, 30), ("beard", 15000, 60)]
    assert (p["open_min"], p["close_min"], p["closed_days"]) == (600, 1200, [0])


def test_request_parser():
    r = parse_request("kal shaam 5 baje haircut", dt.date(2026, 10, 22), ["haircut", "beard"])
    assert (r["service"], r["date"], r["time"], r["missing"]) == ("haircut", TOMORROW, "17:00", [])
    r = parse_request("book beard tomorrow 11:30 am", dt.date(2026, 10, 22), ["haircut", "beard"])
    assert (r["date"], r["time"]) == (TOMORROW, "11:30")
    assert parse_request("kuch book karo", dt.date(2026, 10, 22), ["haircut"])["missing"] == ["service", "date", "time"]


def test_slots_respect_hours_and_closed_days(s):
    b = published(s)
    sl = s.get_slots(b, "haircut", TOMORROW)["slots"]
    assert sl[0] == "10:00" and sl[-1] == "19:30"
    assert s.get_slots(b, "haircut", "2026-10-26")["slots"] == []  # Monday closed
    assert s.get_slots(b, "beard", TOMORROW)["slots"][-1] == "19:00"  # 60 min must fit


def test_hold_confirm_and_slot_disappears(s):
    b = published(s)
    h = s.hold_slot(b, "haircut", TOMORROW, "17:00", "Sanika")
    assert h["ok"] and "₹300" in h["read_back"]
    assert "17:00" not in s.get_slots(b, "haircut", TOMORROW)["slots"]
    c = s.confirm_booking(h["hold_id"], "k1")
    assert c["ok"] and c["status"] == "confirmed"


def test_second_customer_cannot_take_same_slot(s):
    b = published(s)
    assert s.hold_slot(b, "haircut", TOMORROW, "17:00", "A")["ok"]
    assert s.hold_slot(b, "haircut", TOMORROW, "17:00", "B")["error"] == "slot_taken"


def test_overlapping_longer_service_blocked(s):
    b = published(s)
    s.hold_slot(b, "haircut", TOMORROW, "17:30", "A")
    assert s.hold_slot(b, "beard", TOMORROW, "17:00", "B")["error"] == "slot_taken"  # 17:00-18:00 overlaps 17:30


def test_two_chairs_allow_two_but_not_three(s):
    b = published(s, resources=2)
    assert s.hold_slot(b, "haircut", TOMORROW, "17:00", "A")["ok"]
    assert s.hold_slot(b, "haircut", TOMORROW, "17:00", "B")["ok"]
    assert s.hold_slot(b, "haircut", TOMORROW, "17:00", "C")["error"] == "slot_taken"


def test_confirm_is_idempotent(s):
    b = published(s)
    h = s.hold_slot(b, "haircut", TOMORROW, "17:00", "A")
    c1 = s.confirm_booking(h["hold_id"], "same")
    c2 = s.confirm_booking(h["hold_id"], "same")
    assert c2["booking_id"] == c1["booking_id"] and c2["replayed"]
    assert s.db.execute("SELECT COUNT(*) FROM booking").fetchone()[0] == 1
    assert s.confirm_booking(h["hold_id"], "other")["error"] == "hold_confirmed"  # new key, spent hold
    h2 = s.hold_slot(b, "haircut", TOMORROW, "18:00", "A")
    assert s.confirm_booking(h2["hold_id"], "same")["error"] == "idempotency_key_reused"


def test_hold_expires_and_frees_slot(s):
    t = {"now": NOW}
    s.clock = lambda: t["now"]
    b = published(s)
    h = s.hold_slot(b, "haircut", TOMORROW, "17:00", "A")
    t["now"] = NOW + dt.timedelta(seconds=121)
    assert s.confirm_booking(h["hold_id"], "k")["error"] == "hold_expired"
    assert s.hold_slot(b, "haircut", TOMORROW, "17:00", "B")["ok"]


def test_cancel_frees_slot_and_is_repeatable(s):
    b = published(s)
    c = s.confirm_booking(s.hold_slot(b, "haircut", TOMORROW, "17:00", "A")["hold_id"], "k")
    assert s.cancel_booking(c["booking_id"])["already_cancelled"] is False
    assert s.cancel_booking(c["booking_id"])["already_cancelled"] is True
    assert "17:00" in s.get_slots(b, "haircut", TOMORROW)["slots"]


def test_past_and_out_of_hours_rejected(s):
    b = published(s)
    assert s.hold_slot(b, "haircut", "2026-10-22", "08:00", "A")["error"] == "unavailable"
    assert s.hold_slot(b, "haircut", TOMORROW, "21:00", "A")["error"] == "unavailable"
    assert s.hold_slot(b, "haircut", TOMORROW, "17:10", "A")["error"] == "unavailable"


def test_concurrent_holds_only_one_wins(tmp_path):
    s = Store(str(tmp_path / "t.db"), clock=lambda: NOW)
    b = published(s)
    results = []

    def go(i):
        results.append(s.hold_slot(b, "haircut", TOMORROW, "17:00", f"c{i}")["ok"])

    th = [threading.Thread(target=go, args=(i,)) for i in range(20)]
    [t.start() for t in th]
    [t.join() for t in th]
    assert results.count(True) == 1


def test_waitlist_offer_on_cancel_then_confirm(s):
    b = published(s)
    c = s.confirm_booking(s.hold_slot(b, "haircut", TOMORROW, "17:00", "Sanika")["hold_id"], "k1")
    assert s.join_waitlist(b, "haircut", TOMORROW, "18:00", "X")["error"] == "slot_free"
    w = s.join_waitlist(b, "haircut", TOMORROW, "17:00", "Rahul")
    assert w["ok"] and s.join_waitlist(b, "haircut", TOMORROW, "17:00", "Rahul")["already_waiting"]
    assert s.check_waitlist(w["waitlist_id"])["state"] == "waiting"
    assert s.cancel_booking(c["booking_id"])["waitlist_offered"] is True
    o = s.check_waitlist(w["waitlist_id"])
    assert o["state"] == "offered" and "Rahul" in o["read_back"]
    # the offered slot is held for Rahul: a stranger cannot take it
    assert s.hold_slot(b, "haircut", TOMORROW, "17:00", "Stranger")["error"] == "slot_taken"
    assert s.confirm_booking(o["hold_id"], "k2")["ok"]
    assert s.check_waitlist(w["waitlist_id"])["state"] == "booked"


def test_waitlist_first_in_line_wins_and_offer_expires(s):
    t = {"now": NOW}
    s.clock = lambda: t["now"]
    b = published(s)
    c = s.confirm_booking(s.hold_slot(b, "haircut", TOMORROW, "17:00", "A")["hold_id"], "k1")
    w1 = s.join_waitlist(b, "haircut", TOMORROW, "17:00", "First")["waitlist_id"]
    t["now"] = NOW + dt.timedelta(seconds=1)
    w2 = s.join_waitlist(b, "haircut", TOMORROW, "17:00", "Second")["waitlist_id"]
    s.cancel_booking(c["booking_id"])
    assert s.check_waitlist(w1)["state"] == "offered" and s.check_waitlist(w2)["state"] == "waiting"
    t["now"] = NOW + dt.timedelta(seconds=200)
    assert s.check_waitlist(w1)["state"] == "expired"
    assert "17:00" in s.get_slots(b, "haircut", TOMORROW)["slots"]


def test_day_view_shows_bookings_and_holds(s):
    b = published(s)
    s.confirm_booking(s.hold_slot(b, "haircut", TOMORROW, "17:00", "A")["hold_id"], "k")
    s.hold_slot(b, "beard", TOMORROW, "11:00", "B")
    v = s.day_view(b, TOMORROW)
    kinds = sorted((i["kind"], i["start"], i["customer"]) for i in v["items"])
    assert kinds == [("booking", "17:00", "A"), ("hold", "11:00", "B")]
    assert v["items"][0]["start"] and v["open_min"] == 600


def test_race_20_customers_one_slot_two_chairs(tmp_path):
    s = Store(str(tmp_path / "r.db"), clock=lambda: NOW)
    b = published(s, resources=2)
    res = []
    th = [threading.Thread(target=lambda i=i: res.append(s.hold_slot(b, "haircut", TOMORROW, "17:00", f"c{i}")["ok"]))
          for i in range(20)]
    [t.start() for t in th]; [t.join() for t in th]
    assert res.count(True) == 2


def test_request_parser_devanagari_from_hindi_speech():
    today = dt.date(2026, 10, 22)
    r = parse_request("कल शाम 5:00 बजे हेयरकट।", today, ["haircut", "beard"])
    assert (r["service"], r["date"], r["time"], r["missing"]) == ("haircut", TOMORROW, "17:00", [])
    r = parse_request("परसों सुबह ११ बजे दाढ़ी", today, ["haircut", "beard"])
    assert (r["service"], r["date"], r["time"]) == ("beard", "2026-10-24", "11:00")
    r = parse_request("कल मैथ्स क्लास शाम ६ बजे", today, ["maths class", "exam prep"])
    assert (r["service"], r["time"]) == ("maths class", "18:00")
    assert parse_request("exam tomorrow 5 pm", today, ["maths class", "exam prep"])["service"] == "exam prep"
    assert parse_request("शाम", today, ["haircut"])["missing"] == ["service", "date", "time"]


def test_request_parser_devanagari():
    today = dt.date(2026, 10, 22)
    r = parse_request("कल शाम 5:00 बजे हेयरकट", today, ["haircut", "beard"])
    assert (r["service"], r["date"], r["time"], r["missing"]) == ("haircut", TOMORROW, "17:00", [])
    r = parse_request("परसों सुबह ११ बजे दाढ़ी", today, ["haircut", "beard"])
    assert (r["service"], r["date"], r["time"]) == ("beard", "2026-10-24", "11:00")
    r = parse_request("आज दोपहर 2 बजे कंसल्टेशन", today, ["consultation", "follow up"])
    assert (r["service"], r["date"], r["time"]) == ("consultation", "2026-10-22", "14:00")
    assert parse_request("शनिवार शाम 6 बजे मैथ्स", today, ["maths class"])["date"] == "2026-10-24"


def test_audit_is_business_scoped_and_records_rejections(s):
    a = published(s)
    p = parse_onboarding("haircut 300, open 10-8")
    d = s.onboard("Other", p["services"], p["open_min"], p["close_min"], p["closed_days"])
    s.onboard("", [], 0, 1, [], approve_code=d["approve_code"], business_id=d["business_id"])
    h = s.hold_slot(a, "haircut", TOMORROW, "17:00", "X")
    s.hold_slot(a, "haircut", TOMORROW, "17:00", "Y")  # conflict
    s.confirm_booking(h["hold_id"], "k")
    ev = [e["event"] for e in s.audit_list(a)["events"]]
    assert "rejected_slot_taken" in ev and "confirmed" in ev and "held" in ev and "published" in ev
    other = [e["event"] for e in s.audit_list(d["business_id"])["events"]]
    assert other == ["published", "draft_created"] or sorted(other) == ["draft_created", "published"]
    assert s.audit_list("nope")["error"] == "not_found"


def test_audit_records_expired_hold(s):
    t = {"now": NOW}
    s.clock = lambda: t["now"]
    b = published(s)
    h = s.hold_slot(b, "haircut", TOMORROW, "17:00", "A")
    t["now"] = NOW + dt.timedelta(seconds=300)
    assert s.confirm_booking(h["hold_id"], "k")["error"] == "hold_expired"
    ev = [e["event"] for e in s.audit_list(b)["events"]]
    assert "hold_expired" in ev


def test_onboarding_flags_what_was_assumed():
    p = parse_onboarding("haircut 300, beard 150 60min")
    assert p["hours_assumed"] is True
    assert [x["minutes_assumed"] for x in p["services"]] == [True, False]
    assert parse_onboarding("haircut 300 45min, open 9-5")["hours_assumed"] is False
<<<<<<< HEAD


def test_wrong_approve_codes_lock_the_draft(tmp_path):
    from voicestack.store import MAX_APPROVE_FAILS
    s = Store(str(tmp_path / "a.db"))
    d = s.onboard("Lock Shop", [{"name": "haircut", "price_paise": 30000, "minutes": 30}], 600, 1200, [], 1)
    bid, code = d["business_id"], d["approve_code"]
    for i in range(MAX_APPROVE_FAILS):
        r = s.onboard("", [], 0, 1, [], approve_code="000000", business_id=bid)
        assert r["error"] == "bad_code"
    r = s.onboard("", [], 0, 1, [], approve_code=code, business_id=bid)   # even the right code is refused now
    assert r["error"] == "locked"
    assert s.find_businesses()["businesses"] == []
    events = [a["event"] for a in s.audit_list(bid, 50)["events"]]
    assert "approve_rejected" in events and "approve_locked" in events
=======
>>>>>>> c4cefaabec17b67be0d42b87673b30d9cf43d1e1
