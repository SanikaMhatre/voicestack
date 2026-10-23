"""VoiceStack MCP server (Streamable HTTP, stateless JSON) + simulated Alexa+ demo page.

Run:  python -m voicestack.server      ->  MCP at http://localhost:8000/mcp , demo at http://localhost:8000/
<<<<<<< HEAD
HTTP hardening (origin checks, rate limit, headers, logs) lives in voicestack/security.py. There is no authentication.
=======
>>>>>>> c4cefaabec17b67be0d42b87673b30d9cf43d1e1
"""
from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP
<<<<<<< HEAD
from mcp.server.transport_security import TransportSecuritySettings
=======
>>>>>>> c4cefaabec17b67be0d42b87673b30d9cf43d1e1
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from .parser import parse_onboarding, parse_request
<<<<<<< HEAD
from .security import Hardening, Settings
=======
>>>>>>> c4cefaabec17b67be0d42b87673b30d9cf43d1e1
from .store import IST, Store

import datetime as dt

<<<<<<< HEAD
settings = Settings.from_env()
store = Store(os.environ.get("VOICESTACK_DB", "voicestack.db"))
mcp = FastMCP("voicestack", stateless_http=True, json_response=True,
              host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")),
              transport_security=TransportSecuritySettings(
                  enable_dns_rebinding_protection=True,
                  allowed_hosts=list(settings.allowed_hosts), allowed_origins=list(settings.allowed_origins)))
=======
store = Store(os.environ.get("VOICESTACK_DB", "voicestack.db"))
mcp = FastMCP("voicestack", stateless_http=True, json_response=True,
              host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))
>>>>>>> c4cefaabec17b67be0d42b87673b30d9cf43d1e1
WEB = Path(__file__).resolve().parent.parent / "web"


@mcp.tool()
def onboard_business(name: str = "", description: str = "", business_id: str = "", approve_code: str = "",
                     resources: int = 1) -> dict:
    """Owner onboarding in two steps. Step 1: give name + free-text description such as
    'haircut 300, beard 150, open 10-8, closed monday'; returns a DRAFT and an approve_code.
    Step 2: call again with business_id + approve_code to publish. Nothing is bookable until published."""
    if business_id and approve_code:
        return store.onboard("", [], 0, 1, [], approve_code=approve_code, business_id=business_id)
    p = parse_onboarding(description)
    if not p["services"]:
        return {"ok": False, "error": "no_services",
                "message": "Could not find any 'service price' pairs, e.g. 'haircut 300, beard 150'."}
    out = store.onboard(name, p["services"], p["open_min"], p["close_min"], p["closed_days"], resources)
    if out.get("ok"):  # the draft is never silently "complete": say what was assumed
        w = [f"No duration given for '{x['name']}'; assumed {x['minutes']} minutes. Please confirm." for x in p["services"] if x["minutes_assumed"]]
        if p["hours_assumed"]:
            w.append("No opening hours found; assumed 10:00-20:00. Please confirm.")
        if not p["closed_days"]:
            w.append("No closed day found; the shop is treated as open every day. Please confirm.")
        out["warnings"] = w
    return out


@mcp.tool()
def find_businesses(query: str = "") -> dict:
    """List published local businesses, optionally filtered by words in the name or services."""
    return store.find_businesses(query)


@mcp.tool()
def get_slots(business_id: str, service: str, date: str) -> dict:
    """Free start times (HH:MM, India time) for a service on a date (YYYY-MM-DD)."""
    return store.get_slots(business_id, service, date)


@mcp.tool()
def hold_slot(business_id: str, service: str, date: str, time: str, customer_name: str) -> dict:
    """Temporarily hold a slot for 2 minutes and return a read_back sentence to say to the customer.
    Nothing is booked until confirm_booking is called after the customer says yes."""
    return store.hold_slot(business_id, service, date, time, customer_name)


@mcp.tool()
def confirm_booking(hold_id: str, idempotency_key: str) -> dict:
    """Confirm a hold after the customer agrees. Safe to retry with the same idempotency_key."""
    return store.confirm_booking(hold_id, idempotency_key)


@mcp.tool()
def cancel_booking(booking_id: str) -> dict:
    """Cancel a confirmed booking and free its slot. Safe to repeat."""
    return store.cancel_booking(booking_id)


@mcp.tool()
def join_waitlist(business_id: str, service: str, date: str, time: str, customer_name: str) -> dict:
    """Join the waitlist for a slot that is currently taken. If it is cancelled, the longest-waiting
    customer gets a 2-minute hold. Poll check_waitlist with the returned waitlist_id."""
    return store.join_waitlist(business_id, service, date, time, customer_name)


@mcp.tool()
def check_waitlist(waitlist_id: str) -> dict:
    """State of a waitlist entry: waiting, offered (returns hold_id to pass to confirm_booking), booked or expired."""
    return store.check_waitlist(waitlist_id)


DEMO_SHOPS = [
    ("Raj Salon", "haircut 300, beard 150 60min, open 10-8, closed sunday", 1),
    ("Dr. Mehta Clinic", "consultation 500, follow up 300, open 9-5, closed sunday", 2),
    ("Anita Maths Tutor", "maths class 400 60min, exam prep 600 60min, open 4-9, closed saturday", 1),
]


@mcp.custom_route("/api/seed", methods=["POST"])
async def api_seed(request: Request) -> JSONResponse:
<<<<<<< HEAD
    """Demo-only: create and publish three sample shops (skips ones that already exist).
    Production shops go through the owner-approval flow; set VOICESTACK_ENABLE_SEED=0 to switch this off."""
    if not settings.enable_seed:
        return JSONResponse({"ok": False, "error": "disabled", "message": "Sample data is switched off on this server."}, status_code=404)
=======
    """Demo-only: create and publish three sample shops (skips ones that already exist). Production shops go through the owner-approval flow."""
>>>>>>> c4cefaabec17b67be0d42b87673b30d9cf43d1e1
    have = {b["name"] for b in store.find_businesses()["businesses"]}
    made = []
    for name, text, chairs in DEMO_SHOPS:
        if name in have:
            continue
        p = parse_onboarding(text)
        d = store.onboard(name, p["services"], p["open_min"], p["close_min"], p["closed_days"], chairs)
        store.onboard("", [], 0, 1, [], approve_code=d["approve_code"], business_id=d["business_id"])
        made.append(name)
    return JSONResponse({"ok": True, "created": made})


@mcp.custom_route("/api/day", methods=["GET"])
async def api_day(request: Request) -> JSONResponse:
    """Read-only owner calendar for the demo page."""
    q = request.query_params
    return JSONResponse(store.day_view(q.get("business_id", ""), q.get("date", "")))


@mcp.custom_route("/api/audit", methods=["GET"])
async def api_audit(request: Request) -> JSONResponse:
    """Read-only, business-scoped change log for the owner view (includes rejected attempts)."""
    q = request.query_params
<<<<<<< HEAD
    try:
        limit = max(1, min(200, int(q.get("limit", "50") or 50)))
    except ValueError:
        return JSONResponse({"ok": False, "error": "invalid", "message": "limit must be a number."}, status_code=400)
    return JSONResponse(store.audit_list(q.get("business_id", ""), limit))
=======
    return JSONResponse(store.audit_list(q.get("business_id", ""), int(q.get("limit", "50") or 50)))
>>>>>>> c4cefaabec17b67be0d42b87673b30d9cf43d1e1


@mcp.custom_route("/api/parse", methods=["POST"])
async def api_parse(request: Request) -> JSONResponse:
    """Demo-page helper: typed Hindi/English -> {service,date,time}. Rule-based; real Alexa+ does its own language understanding."""
<<<<<<< HEAD
    try:
        body = await request.json()
        text = str(body.get("text", ""))[:500]
        names = [str(n)[:60] for n in list(body.get("service_names", []))[:50]]
    except (ValueError, TypeError, AttributeError):
        return JSONResponse({"ok": False, "error": "invalid", "message": "Send JSON like {\"text\": \"...\", \"service_names\": []}."}, status_code=400)
    today = dt.datetime.now(IST).date()
    return JSONResponse(parse_request(text, today, names))
=======
    body = await request.json()
    names = body.get("service_names", [])
    today = dt.datetime.now(IST).date()
    return JSONResponse(parse_request(str(body.get("text", "")), today, names))
>>>>>>> c4cefaabec17b67be0d42b87673b30d9cf43d1e1


@mcp.custom_route("/api/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    """Lets the demo page detect an out-of-date server."""
<<<<<<< HEAD
    return JSONResponse({"ok": True, "version": 4, "tools": 8})


@mcp.custom_route("/api/ready", methods=["GET"])
async def ready(request: Request) -> JSONResponse:
    """Readiness probe: the database answers."""
    try:
        store.db.execute("SELECT 1").fetchone()
    except Exception:
        return JSONResponse({"ok": False, "error": "db_unavailable"}, status_code=503)
    return JSONResponse({"ok": True})
=======
    return JSONResponse({"ok": True, "version": 3, "tools": 8})
>>>>>>> c4cefaabec17b67be0d42b87673b30d9cf43d1e1


@mcp.custom_route("/favicon.ico", methods=["GET"])
async def favicon(request: Request) -> Response:
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect width="40" height="40" rx="12" fill="#134a45"/><path d="M8 19h5l3-7 4.5 14 3-7H31" fill="none" stroke="#b8e6cc" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/><circle cx="30.5" cy="31" r="3.2" fill="#e8795c"/></svg>'
    return Response(svg, media_type="image/svg+xml")


@mcp.custom_route("/", methods=["GET"])
async def index(request: Request) -> FileResponse:
    return FileResponse(WEB / "index.html")


<<<<<<< HEAD
app = mcp.streamable_http_app()
app.add_middleware(Hardening, settings=settings)


def main() -> None:
    import logging
    import uvicorn
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    host, port = mcp.settings.host, mcp.settings.port
    print(f"VoiceStack  MCP: http://{host}:{port}/mcp   Demo: http://{host}:{port}/")
    uvicorn.run(app, host=host, port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
=======
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
>>>>>>> c4cefaabec17b67be0d42b87673b30d9cf43d1e1
