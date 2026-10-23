# VoiceStack: User Guide

For anyone using the demo page. (Developers: see `TECHNICAL_DOCUMENTATION.md`.)

## Start it
1. Open a terminal **inside the project folder** and run `python -m voicestack.server`. Leave the terminal open.
2. Open **http://localhost:8000/** in Chrome.
3. Press the **?** button (top right) any time for a quick tour.

The page has three tabs: **Customer**, **Shop owner**, **Developer**. The drop-down at the top chooses which shop you are working with.

## A two-minute tour
1. **Shop owner** tab → **Load 3 sample shops (demo)**.
2. **Customer** tab → tap a suggestion such as *kal shaam 5 baje haircut*.
3. The assistant reads the appointment back and holds it for 2 minutes. Press **Yes, confirm**. A receipt appears.
4. Press **Another customer wants this slot**: a second person is refused and joins the waitlist.
5. Press **Cancel my booking**: the waiting customer is offered the slot.
6. **Shop owner** tab: see the bookings table, calendar and audit log, including the refused attempt.
7. **Developer** tab → **Run the race**: 20 customers ask for one slot at once, exactly one wins.

## Customer tab
- **Type** what you want, or press 🎤 and **speak** (Hindi or English; choose the language beside the box). Your words appear in the box so you can correct them, then press **Send**.
- The assistant needs three things: **which service**, **which day**, **what time**. It asks for what is missing and remembers what you already said.
- Examples: `kal shaam 5 baje haircut` · `परसों सुबह 11 बजे दाढ़ी` · `book beard tomorrow 4:30 pm`.
- The coloured badge shows what is really happening: *Held, Confirming, Confirmed, Hold expired, Conflict, Outcome unknown*.
- A booking happens **only** after you press **Yes, confirm** (or say *haan / yes*). The hold lasts 2 minutes.
- If the time is taken you get free times to tap, or you can **Join waitlist**.
- **Read replies aloud** speaks the assistant's answers.

## Shop owner tab
1. **Set up your shop:** type a name and paste a message, for example `haircut 300 30min, beard 150 60min, open 10-8, closed sunday`, then press **Extract draft**.
2. Read the **preview**. Amber warnings list anything the system *assumed* (for example a missing duration). Edit the message and extract again if needed.
3. Press **Approve & publish**. Only then can customers book.
4. **Bookings:** pick a date, filter by status, press **Cancel** to cancel a booking. Totals count what is recorded; "scheduled value" is not revenue.
5. **Audit log:** every change for this shop, including refused attempts (slot taken, expired hold).

## Developer tab
- **Request inspector:** every MCP call the page makes, with tool, outcome and time. Request contents are hidden unless you tick the raw log.
- **Latency:** p50/p95 per tool with the number of samples. These are browser-to-localhost times, not Alexa+ times.
- **Try to break it:** run N customers against one slot.
- **Server:** version and the eight tools.

## Starting fresh
Stop the server (Ctrl+C), delete the `voicestack.db` file in the project folder, start it again.

## If something looks wrong
| You see | Do this |
|---|---|
| A red banner about an OLD server | Stop the old server, start from the new folder, press Ctrl+Shift+R |
| No shops in the list | Shop owner tab → Load 3 sample shops, or publish your own |
| The mic is missing or mishears | Use Chrome; or type |
| "Slot was just taken" | Pick another time, or join the waitlist |
