# VoiceStack

**A voice booking backend for local businesses, built as a self-hosted MCP server.**

Customers book by speaking Hindi or English. Shop owners set up once by pasting a message. VoiceStack holds the slot, reads the booking back, and confirms it once, with no double-bookings and safe retries.

Built for the Amazon "Build, Ship, Shape" Developer Hackathon (Alexa+ track). MIT licensed.

## Features
- **MCP server** over Streamable HTTP (spec 2025-11-25) at `/mcp`, with eight tools.
- **No double-booking:** a database constraint plus transactions; 20 simultaneous requests for one slot produce exactly one winner.
- **Safe retries:** `confirm_booking` accepts an `idempotency_key`, so a repeated call returns the same booking.
- **Two-minute holds** that expire on their own, then free the slot.
- **Waitlist:** when a booking is cancelled, the longest-waiting customer is offered the slot.
- **Owner approval:** a shop is bookable only after the owner approves the draft with a code.
- **Audit log** per shop, including refused attempts.
- **Hindi and English:** Devanagari and Roman Hindi, rule-based, no language model.
- **Demo page** with three views: Customer, Shop owner, Developer.

## Tech stack
Python, official MCP Python SDK (FastMCP, `mcp==1.30.0`), SQLite, and a single-file vanilla JavaScript page. No LLM, no cloud services, no API keys.

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m voicestack.server
```
- MCP endpoint: http://localhost:8000/mcp
- Demo page: http://localhost:8000/

Run from the project folder. In a second terminal:
```bash
pytest -q                      # 33 tests
python scripts/mcp_smoke.py    # end-to-end check through a real MCP client
```

## Try the demo
1. **Shop owner** tab: click **Load 3 sample shops** (adds only missing shops, never duplicates).
2. **Customer** tab: tap a suggestion such as *kal shaam 5 baje haircut*, or use the mic, then press **Yes, confirm**.
3. **Developer** tab: press **Run the race** to see 20 customers compete for one slot.

The **?** button on the page opens a short tour.

## MCP tools
| Tool | What it does |
|---|---|
| `onboard_business` | Owner text becomes a **draft**; nothing is bookable until the owner publishes with the `approve_code` |
| `find_businesses` | Lists published businesses |
| `get_slots` | Free start times for a service and date (India time) |
| `hold_slot` | Holds a slot for 2 minutes and returns a read-back sentence |
| `confirm_booking` | Confirms a hold; safe to retry with the same `idempotency_key` |
| `cancel_booking` | Frees the slot; safe to repeat; offers it to the next person waiting |
| `join_waitlist` | Queues for a taken slot, first come first served |
| `check_waitlist` | Returns waiting, offered, booked or expired |

## How it stays correct
- A **primary key on `occupancy(business_id, resource_id, start)`** inside `BEGIN IMMEDIATE` transactions prevents two bookings for one slot.
- Hold expiry is checked in code against the clock.
- `confirm_booking` stores each `(operation, key)` with a request fingerprint; reusing a key for a different hold is rejected.
- Prices are integer paise; all times are Asia/Kolkata.
- No language model writes to the database.

## Security
One middleware (`voicestack/security.py`) covers every route: host and origin allow-list, rate limit, 1 MiB body cap, security headers, a structured access log with request ids that never contains request bodies or customer names, and a lock after five wrong approval codes. Health probes: `/api/health`, `/api/ready`. Settings are listed in the technical documentation, section 15.2.

## Documentation
- [Technical documentation](docs/TECHNICAL_DOCUMENTATION.md): architecture, data model, API reference, flows, security, testing, run book.
- [User guide](docs/USER_GUIDE.md): how to use the three views.

## Limitations
- Not tested on a real Alexa+ device. The demo page is an MCP client with typed or browser-recognised speech standing in for Alexa+.
- No authentication or account linking; every tool and route is public. Anyone holding a `booking_id` or `hold_id` can act on it. A real deployment would add OAuth 2.1 with PKCE.
- `/api/day` and `/api/audit` are unauthenticated, and `/api/seed` (demo only) skips owner approval. Do not use real customer data.
- The parser is rule-based: common Hindi (Devanagari and Roman) and English phrases and a built-in list of service words, not free-form language. "kal" is always read as tomorrow.
- One timezone (Asia/Kolkata), 30-minute booking blocks, no payments.
- Waitlist: if an offer expires unclaimed, the slot becomes free again and is not passed to the next waiter.
- Voice on the demo page uses the browser's speech feature (best in Chrome, which may send audio to its vendor); Hindi accuracy depends on the browser.
- Latency on the Developer view is a browser round trip to localhost, not an Alexa+ end-to-end figure.

## Project layout
```
voicestack/store.py       booking core and all rules
voicestack/parser.py      rule-based Hindi/English parsing
voicestack/server.py      MCP tools and helper routes
voicestack/security.py    HTTP hardening
web/index.html            demo page (three views)
tests/                    automated tests
scripts/mcp_smoke.py      end-to-end MCP check
docs/                     technical documentation and user guide
```

## License
MIT. See [LICENSE](LICENSE).
