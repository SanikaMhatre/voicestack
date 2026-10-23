"""End-to-end smoke test: talks to a RUNNING VoiceStack server over real MCP (Streamable HTTP).

    python -m voicestack.server        # terminal 1
    python scripts/mcp_smoke.py        # terminal 2   (optional: URL as first argument)

Prints each call and its result, and exits non-zero if any expectation fails.
It uses a throw-away business, so it is safe to run against a demo database.
"""
import asyncio
import datetime as dt
import json
import sys
import uuid
from zoneinfo import ZoneInfo

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/mcp"


def val(r):
    return r.structuredContent.get("result", r.structuredContent) if r.structuredContent else json.loads(r.content[0].text)


async def main() -> int:
    failures = []

    def check(label, cond):
        print(("PASS  " if cond else "FAIL  ") + label)
        if not cond:
            failures.append(label)

    async with streamablehttp_client(URL) as (r, w, _):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            check(f"protocol negotiated ({init.protocolVersion})", bool(init.protocolVersion))
            names = [t.name for t in (await s.list_tools()).tools]
            check("8 tools advertised", len(names) == 8)

            async def call(tool_name, **args):
                out = val(await s.call_tool(tool_name, args))
                print(f"  {tool_name}({json.dumps(args)}) -> {json.dumps(out)[:200]}")
                return out

            tag = uuid.uuid4().hex[:4]
            d = await call("onboard_business", name=f"Smoke {tag}", description="haircut 300 30min, open 10-8, closed sunday")
            check("draft is not yet bookable", (await call("find_businesses", query=f"Smoke {tag}"))["businesses"] == [])
            pub = await call("onboard_business", business_id=d["business_id"], approve_code=d["approve_code"])
            check("owner publishes", pub.get("status") == "published")
            b = d["business_id"]
            day = dt.datetime.now(ZoneInfo("Asia/Kolkata")).date() + dt.timedelta(days=2)
            while day.weekday() == 6:  # shop is closed on Sundays
                day += dt.timedelta(days=1)
            day = day.isoformat()
            h = await call("hold_slot", business_id=b, service="haircut", date=day, time="17:00", customer_name="Smoke")
            check("hold granted", h.get("ok") is True)
            rival = await call("hold_slot", business_id=b, service="haircut", date=day, time="17:00", customer_name="Rival")
            check("second customer gets slot_taken", rival.get("error") == "slot_taken")
            key = str(uuid.uuid4())
            c1 = await call("confirm_booking", hold_id=h["hold_id"], idempotency_key=key)
            c2 = await call("confirm_booking", hold_id=h["hold_id"], idempotency_key=key)
            check("retry with same key returns same booking", c1.get("booking_id") == c2.get("booking_id") and c2.get("replayed") is True)
            c = await call("cancel_booking", booking_id=c1["booking_id"])
            check("cancel frees the slot", c.get("ok") is True and "17:00" in (await call("get_slots", business_id=b, service="haircut", date=day))["slots"])
    print("\n%d failure(s)" % len(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
