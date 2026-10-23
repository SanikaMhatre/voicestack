# VoiceStack

A Hindi/English voice booking gateway for local businesses, exposed as a self-hosted **MCP server**
(Streamable HTTP, spec 2025-11-25) for the Alexa+ track. A shop owner sets up once; a voice assistant books slots
with no double-bookings, safe retries and owner approval.

Built for the Amazon "Build, Ship, Shape" Developer Hackathon. MIT licensed.

<<<<<<< HEAD
Stack: Python, the official MCP Python SDK (FastMCP, pinned `mcp==1.30.0`), SQLite, and a single-file vanilla JS demo page. No LLM, no cloud services, no API keys.

=======
>>>>>>> c4cefaabec17b67be0d42b87673b30d9cf43d1e1
## Run it (no keys, no cloud, no cost)

```bash
python -m venv .venv && source .venv/bin/activate
<<<<<<< HEAD
pip install -r requirements-dev.txt
python -m voicestack.server        # MCP: http://localhost:8000/mcp   Demo page: http://localhost:8000/
pytest -q                          # 33 tests
python scripts/mcp_smoke.py       # end-to-end MCP check against the running server (second terminal)
```

Container (not built or run in the environment where this was written, so treat it as untested):
`docker build -t voicestack . && docker run --rm -p 127.0.0.1:8000:8000 -v voicestack-data:/data voicestack`

=======
pip install -r requirements.txt
python -m voicestack.server        # MCP: http://localhost:8000/mcp   Demo page: http://localhost:8000/
pytest -q                          # 22 tests
python scripts/mcp_smoke.py       # end-to-end check against the running server (second terminal)
```

>>>>>>> c4cefaabec17b67be0d42b87673b30d9cf43d1e1
## Eight MCP tools
| Tool | What it does |
|---|---|
| `onboard_business` | Owner text → **draft**; nothing bookable until the owner publishes with the `approve_code` |
| `find_businesses` | Published businesses only |
| `get_slots` | Free start times for a service/date (India time) |
| `hold_slot` | 2-minute hold + a read-back sentence for the customer |
| `confirm_booking` | Confirms a hold; safe to retry with the same `idempotency_key` |
| `cancel_booking` | Frees the slot; safe to repeat. If someone is waiting, they are offered it |
| `join_waitlist` | Queue for a taken slot (first come, first served) |
| `check_waitlist` | waiting / offered (with a 2-minute hold to confirm) / booked / expired |

## Documentation
- [`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md): architecture, data model, algorithms, API reference, flows, security, testing, run book, limits.
- [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md): how to use the three views.

<<<<<<< HEAD
The demo page uses the VoiceStack colours (forest green, cream, mint, coral) with a dark mode that follows the browser setting.

=======
>>>>>>> c4cefaabec17b67be0d42b87673b30d9cf43d1e1
## The demo page
Three separate views (tabs): **Customer**, **Shop owner**, **Developer**. A **?** button opens a built-in tour. Open http://localhost:8000/ : in the Shop owner tab click "Load 3 sample shops", then in the Customer tab talk to the assistant by typing or with the mic
(browser speech recognition, Hindi or English, optional spoken replies). It shows a live owner calendar with holds counting down,
a "Run the race" panel (20 customers grab one slot at the same instant; exactly as many win as there are chairs),
a retry-confirm button (no duplicate booking), and a waitlist that offers a cancelled slot to the next person.
<<<<<<< HEAD
The wire log shows every real MCP call. "Load 3 sample shops" adds only the shops that are missing, so clicking it again does not create duplicates.

## Hardening (closer to production)
One middleware (`voicestack/security.py`) sits in front of every route:
- **No login in this demo:** every tool and route is public. The protections below limit abuse; they are not authentication.
- **Host and Origin allow-list** (DNS-rebinding and cross-site protection), a **rate limit**, a **1 MiB body cap**, and security headers including a Content-Security-Policy.
- **Approval-code lock:** five wrong codes lock a draft.
- **Structured JSON access log** with a request id (`X-Request-ID`); never logs request bodies or customer names. Probes: `/api/health`, `/api/ready`.
- `Dockerfile` (non-root, `/data` volume, health check) and a GitHub Actions workflow (tests on Python 3.12/3.13, end-to-end MCP check, image build).

All settings are in [docs §12.4](docs/TECHNICAL_DOCUMENTATION.md). There is **no authentication and no OAuth**.
=======
The wire log shows every real MCP call.
>>>>>>> c4cefaabec17b67be0d42b87673b30d9cf43d1e1

## Why it is reliable
- Double-booking is prevented by a **PRIMARY KEY on `occupancy(business_id, resource_id, start)`** inside `BEGIN IMMEDIATE` transactions (tested with 20 concurrent threads: exactly one wins).
- Holds expire; expiry is compared in code against the clock, not by a TTL feature.
- `confirm_booking` stores `(operation, key) → response` with a request fingerprint; replays return the same booking, and reusing a key for a different hold is rejected.
- Prices are integer paise. Times are Asia/Kolkata.
- No language model writes to the database. The parser is rule-based (`voicestack/parser.py`).

<<<<<<< HEAD
## Limitations
- Not tested on a real Alexa+ device. The demo page is an MCP client with typed or browser-recognised speech standing in for Alexa+.
- No authentication or account linking. Anyone holding a `booking_id` or `hold_id` can act on it. A real deployment would add OAuth 2.1 with PKCE.
- The helper routes `/api/day` and `/api/audit` are unauthenticated, and `/api/seed` (demo only) skips owner approval. Do not use real customer data.
- The parser is rule-based. It understands common Hindi (Devanagari and Roman) and English phrases and a built-in list of service words, not free-form language. "kal" is always read as tomorrow.
- One timezone (Asia/Kolkata), 30-minute booking blocks, no payments.
- Waitlist: an offer goes to the longest-waiting person when a booking is cancelled. If the offer expires unclaimed, the slot becomes free again and is not passed to the next waiter.
- Voice on the demo page uses the browser's speech feature (best in Chrome, which may send audio to its vendor). Accuracy for Hindi depends on the browser.
- The latency shown on the Developer view is a browser round trip to localhost, not an Alexa+ end-to-end figure.

## Layout
`voicestack/store.py` booking core · `voicestack/parser.py` rule-based parsing · `voicestack/server.py` MCP tools · `voicestack/security.py` HTTP hardening · `web/index.html` demo (3 views) · `tests/` · `scripts/mcp_smoke.py` · `Dockerfile` · `.github/workflows/ci.yml` · `docs/`
=======
## Honest limits
- **Not tested on a real Alexa+ device or the Alexa+ add-on tooling**, which is not available to participants. The demo page is a real MCP client talking to the server, with typed text standing in for speech.
- **No account linking / OAuth.** Anyone with a `booking_id` or `hold_id` (long random values) can act on it. Real deployment would add OAuth 2.1 + PKCE.
- The parser understands Hindi in Devanagari and Roman letters for common words (days, times, "baje", "shaam") and a built-in list of service words (haircut, beard, consultation, maths...). A custom service the owner names in another script may not be recognised.
- The Hindi/English parser covers common phrases ("kal shaam 5 baje haircut") but is not a full language model; "kal" is read as *tomorrow*.
- One timezone, 30-minute booking blocks, no payments.
- Waitlist: an offer goes to the longest-waiting person only when a booking is cancelled. If that offer expires unclaimed, the slot is simply free again; it is not passed on to the next waiter.
- Voice in the demo page uses the browser's own speech feature (best in Chrome, which may send audio to its vendor). Hindi accuracy depends on the browser, and I have not tested it with real speech.
- `/api/seed` creates sample shops without the owner-approval step; it is demo-only.
- Latency in the demo's wire log is a browser round trip to localhost, not an Alexa+ end-to-end measurement.

## Layout
`voicestack/store.py` booking core · `voicestack/parser.py` rule-based parsing · `voicestack/server.py` MCP tools · `web/index.html` demo (3 views) · `tests/` · `scripts/mcp_smoke.py` · `docs/`
>>>>>>> c4cefaabec17b67be0d42b87673b30d9cf43d1e1
