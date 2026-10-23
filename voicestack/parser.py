"""Rule-based Hindi/English parsing. No network, no model. Pure functions."""
from __future__ import annotations

import datetime as dt
import re

DAYS = {"monday": 0, "mon": 0, "somvar": 0, "somwar": 0, "tuesday": 1, "tue": 1, "mangalvar": 1, "mangalwar": 1,
        "wednesday": 2, "wed": 2, "budhvar": 2, "budhwar": 2, "thursday": 3, "thu": 3, "guruvar": 3, "guruwar": 3,
        "friday": 4, "fri": 4, "shukravar": 4, "shukrawar": 4, "saturday": 5, "sat": 5, "shanivar": 5, "shaniwar": 5,
        "sunday": 6, "sun": 6, "ravivar": 6, "raviwar": 6, "itwar": 6, "itvar": 6,
        "सोमवार": 0, "मंगलवार": 1, "बुधवार": 2, "गुरुवार": 3, "शुक्रवार": 4, "शनिवार": 5, "रविवार": 6, "इतवार": 6}

# Hindi (Devanagari) spellings of service words, so speech recognition output in Devanagari still matches.
ALIASES = {
    "haircut": ["हेयरकट", "हेयर कट", "बाल कटवा", "कटिंग"],
    "beard": ["बियर्ड", "दाढ़ी", "दाढी", "शेव"],
    "consultation": ["कंसल्टेशन", "कन्सल्टेशन", "परामर्श", "डॉक्टर"],
    "follow up": ["फॉलो अप", "फॉलोअप", "फॉलो-अप"],
    "maths": ["मैथ्स", "मैथ", "गणित"],
    "exam prep": ["एग्जाम", "परीक्षा"],
}
_DIG = str.maketrans("०१२३४५६७८९", "0123456789")


def _has(t: str, *words: str) -> bool:
    """Latin words match on word boundaries; Devanagari words match as substrings
    (Python's \\b is unreliable around Devanagari vowel signs)."""
    for w in words:
        if w.isascii():
            if re.search(rf"\b{re.escape(w)}\b", t):
                return True
        elif w in t:
            return True
    return False


def _to_24(h: int, mer: str | None, hint: str | None) -> int:
    if mer == "pm" and h < 12:
        return h + 12
    if mer == "am":
        return 0 if h == 12 else h
    if hint == "pm" and h < 12:
        return h + 12
    if hint == "am":
        return h
    return h + 12 if 1 <= h <= 7 else h  # bare "5 baje" -> 17:00; "10 baje" -> 10:00


def parse_onboarding(text: str) -> dict:
    """'haircut 300, beard 150 45min, open 10-8, closed monday' -> structured draft."""
    t = text.lower().replace("₹", " rs ")
    closed = sorted({DAYS[w] for w in re.findall(r"[a-z]+", t) if w in DAYS and
                     re.search(rf"(closed|band|off)\W+(?:\w+\W+){{0,2}}{w}|{w}\W+(?:\w+\W+){{0,1}}(closed|band|off)", t)})
    open_min, close_min = 10 * 60, 20 * 60
    hours_assumed = True
    m = re.search(r"(\d{1,2})(?::(\d\d))?\s*(am|pm)?\s*(?:to|-|se|–)\s*(\d{1,2})(?::(\d\d))?\s*(am|pm)?", t)
    stripped = t
    if m:
        o = _to_24(int(m[1]), m[3], None) if m[3] else int(m[1])
        c = _to_24(int(m[4]), m[6], None) if m[6] else int(m[4])
        if c <= o:
            c += 12
        open_min, close_min = o * 60 + int(m[2] or 0), c * 60 + int(m[5] or 0)
        hours_assumed = False
        stripped = t.replace(m[0], " ")
    services = []
    for part in re.split(r"[,\n;]|\band\b|\baur\b", stripped):
        sm = re.search(r"([a-zऀ-ॿ][a-zऀ-ॿ ]*?)\s*(?:rs\.?|rupees?|rupaye)?\s*(\d{2,5})\s*(?:(\d{2,3})\s*min)?", part)
        if sm and not re.search(r"\b(open|close|closed|band|off)\b", sm[1]):
            mins = int(sm[3]) if sm[3] else 30
            mins = max(30, round(mins / 30) * 30)
            services.append({"name": sm[1].strip(), "price_paise": int(sm[2]) * 100, "minutes": mins,
                             "minutes_assumed": not sm[3]})
    return {"services": services, "open_min": open_min, "close_min": close_min, "closed_days": closed,
            "hours_assumed": hours_assumed}


# Hindi speech recognition returns Devanagari, so map common words to the Roman forms parsed below.
DEVANAGARI = {
    "परसों": "parso", "परसो": "parso", "कल": "kal", "आज": "aaj", "शाम": "shaam", "सुबह": "subah", "रात": "raat",
    "दोपहर": "dopahar", "बजे": "baje", "सोमवार": "monday", "मंगलवार": "tuesday", "बुधवार": "wednesday",
    "गुरुवार": "thursday", "बृहस्पतिवार": "thursday", "शुक्रवार": "friday", "शनिवार": "saturday", "रविवार": "sunday",
    "हेयरकट": "haircut", "हेअरकट": "haircut", "हेयर कट": "haircut", "बाल कटवाने": "haircut",
    "दाढ़ी": "beard", "दाढी": "beard", "बियर्ड": "beard", "शेव": "beard",
    "कंसल्टेशन": "consultation", "परामर्श": "consultation", "फॉलो अप": "follow up", "फॉलोअप": "follow up",
    "मैथ्स": "maths", "मैथ": "maths", "गणित": "maths", "एग्जाम": "exam", "परीक्षा": "exam", "क्लास": "class",
}
_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def normalize(text: str) -> str:
    t = text.translate(_DIGITS)
    for w in sorted(DEVANAGARI, key=len, reverse=True):
        t = t.replace(w, f" {DEVANAGARI[w]} ")
    return re.sub(r"\s+", " ", t.replace("।", " ")).strip().lower()


def parse_request(text: str, today: dt.date, service_names: list[str]) -> dict:
    """'kal shaam 5 baje haircut' or 'कल शाम 5:00 बजे हेयरकट' -> {service, date, time, missing}.
    'kal'/'कल' is read as tomorrow."""
    t = text.lower().translate(_DIG)
    out: dict = {"service": None, "date": None, "time": None}
    for name in sorted(service_names, key=len, reverse=True):
        n = name.lower()
        if n in t or any(a in t for key, al in ALIASES.items() if key in n for a in al):
            out["service"] = name
            break
    if not out["service"]:  # a single distinctive word, e.g. "exam" -> "exam prep"; only if it is unambiguous
        hits = [n for n in service_names if any(len(w) >= 4 and _has(t, w) for w in n.lower().split())]
        if len(hits) == 1:
            out["service"] = hits[0]
    if _has(t, "aaj", "today", "आज"):
        out["date"] = today
    elif _has(t, "parso", "परसों", "परसो") or "day after tomorrow" in t:
        out["date"] = today + dt.timedelta(days=2)
    elif _has(t, "kal", "tomorrow", "tmrw", "कल"):
        out["date"] = today + dt.timedelta(days=1)
    else:
        iso = re.search(r"\d{4}-\d{2}-\d{2}", t)
        if iso:
            try:
                out["date"] = dt.date.fromisoformat(iso[0])
            except ValueError:
                pass
        else:
            for w in re.findall(r"[a-z\u0900-\u097f]+", t):
                if w in DAYS:
                    out["date"] = today + dt.timedelta(days=(DAYS[w] - today.weekday()) % 7 or 7)
                    break
    hint = "pm" if _has(t, "shaam", "sham", "evening", "raat", "night", "dopahar", "afternoon", "शाम", "रात", "दोपहर") else \
           "am" if _has(t, "subah", "morning", "सुबह") else None
    tm = re.search(r"\b(\d{1,2}):(\d\d)\s*(am|pm)?", t) or \
         re.search(r"\b(\d{1,2})()\s*(am|pm)\b", t) or \
         re.search(r"(\d{1,2})()()\s*(?:baje|bje|o'?clock|बजे)", t)
    if tm:
        h = _to_24(int(tm[1]), tm[3] or None, hint)
        if h < 24:
            out["time"] = f"{h:02d}:{int(tm[2] or 0):02d}"
    out["date"] = out["date"].isoformat() if out["date"] else None
    out["missing"] = [k for k in ("service", "date", "time") if not out[k]]
    return out
