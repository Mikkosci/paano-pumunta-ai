"""Local-AI layer for Paano Pumunta AI.

The local model (default Gemma-2-2b served by LM Studio) interprets messy
Taglish into structured JSON. It NEVER chooses routes -- router.py (Dijkstra)
is the only thing that does that.

Interpreter protocol: a SINGLE user message, no system role.
"""
import json
import re

import requests

DEFAULT_URL = "http://localhost:1234/v1/chat/completions"
DEFAULT_MODEL = "gemma-2-2b"
TIMEOUT = 20  # seconds; slower than this and we fall back to rules

PREFERENCES = ("fastest", "fewest_stops", "fewest_transfers")
FARE_WORDS = ("pamasahe", "pamasahi", "magkano", "fare", "bayad", "price",
              "how much", "magkano'ng")

FARE_DISCLAIMER = ("Hindi kasama ang pamasahe sa app na ito -- madalas magbago "
                   "at madaling magkamali. Tanungin ang driver o tingnan ang "
                   "operator para sa aktwal na pamasahe.")

_SCHEMA_PROMPT = """You extract trip details from a commuter message. Reply with ONLY a JSON object, no other text.

Schema:
{"origin": string or null, "destination": string or null, "preference": "fastest" | "fewest_stops" | "fewest_transfers" or null, "avoid": [strings], "follow_up": true or false}

Rules:
- "origin" and "destination": place names for the start and end of the trip, or null if not mentioned.
- "preference": "fewest_transfers" for fewer transfers ("kaunting lipat", "less transfers"); "fewest_stops" for fewer stops ("kaunting hinto"); "fastest" for fastest or quickest ("mabilis", "mabilisan"); otherwise null.
- "avoid": transport names to exclude, using ONLY words that appear in the message (for example "MRT", "jeep", "LRT"). Empty list if none.
- "follow_up": true if the message continues a previous trip without naming a new origin and destination (for example "paano kung walang MRT", "mas kaunting lipat?"); otherwise false.

Message:
\"\"\"<<<MESSAGE>>>\"\"\"
JSON:"""


def _user_message(user_text, with_schema):
    if with_schema:
        return _SCHEMA_PROMPT.replace("<<<MESSAGE>>>", user_text)
    return ("Reply with ONLY a JSON object like "
            '{"origin": ..., "destination": ..., "preference": ..., '
            '"avoid": [...], "follow_up": ...} for this message: ' + user_text)


def _post(url, model, message, timeout):
    body = {"messages": [{"role": "user", "content": message}],
            "temperature": 0.2, "max_tokens": 300}
    if model.strip():
        body["model"] = model.strip()
    res = requests.post(url, json=body, timeout=timeout)
    if res.status_code != 200:
        return None
    return res.json()["choices"][0]["message"]["content"].strip()


def _extract_json(text):
    """Pull the first balanced {...} object out of text."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _validate(parsed, user_text, router):
    """Validate every field against the route graph. Clean dict or None."""
    if not isinstance(parsed, dict):
        return None
    user_l = user_text.lower()
    origin = router.resolve_place(parsed.get("origin") or "") if parsed.get("origin") else None
    dest = router.resolve_place(parsed.get("destination") or "") if parsed.get("destination") else None
    pref = parsed.get("preference")
    pref = pref if pref in PREFERENCES else None
    avoid = parsed.get("avoid") or []
    if not isinstance(avoid, list):
        avoid = []
    # avoid terms must actually appear in what the user typed
    avoid = [a.strip() for a in avoid
             if isinstance(a, str) and a.strip() and a.strip().lower() in user_l]
    follow_up = bool(parsed.get("follow_up"))
    if origin is None and dest is None and not follow_up and not avoid and pref is None:
        return None  # nothing usable
    return {"origin": origin, "destination": dest, "preference": pref,
            "avoid": avoid, "follow_up": follow_up}


def interpret(user_text, router, url=DEFAULT_URL, model=DEFAULT_MODEL, timeout=TIMEOUT):
    """Ask the local model to structure the message.

    Returns {"result", "raw", "status"} where status is one of:
      "ok"        -- first try parsed and validated
      "ok_retry"  -- second try (simpler prompt) parsed and validated
      "fallback"  -- model down, slow, or output unusable; use rules instead
    """
    raw = None
    try:
        raw = _post(url, model, _user_message(user_text, True), timeout)
    except Exception:
        raw = None
    result = _validate(_extract_json(raw), user_text, router) if raw else None
    status = "ok"
    if result is None and raw is not None:
        try:  # retry once without the schema wording
            raw = _post(url, model, _user_message(user_text, False), timeout)
        except Exception:
            raw = None
        result = _validate(_extract_json(raw), user_text, router) if raw else None
        status = "ok_retry"
    if result is None:
        return {"result": None, "raw": raw, "status": "fallback"}
    return {"result": result, "raw": raw, "status": status}


def phrase_itinerary(facts, url=DEFAULT_URL, model=DEFAULT_MODEL, timeout=TIMEOUT):
    """Rephrase fixed facts in friendly Taglish. Returns text or None."""
    system = ("You are Paano Pumunta AI, a friendly Metro Manila commute guide. Rewrite the ITINERARY "
              "below in short, friendly Taglish (max 5 sentences). Use ONLY facts from the itinerary. "
              "Never add routes, stops or times. Keep every place name exactly. "
              "Never mention fares or prices -- this app does not include fare information. "
              "Say that times are rough estimates.")
    # Gemma's chat template rejects the "system" role, so send one user message
    body = {"messages": [{"role": "user", "content": system + "\n\nITINERARY:\n" + facts}],
            "temperature": 0.3, "max_tokens": 300}
    if model.strip():
        body["model"] = model.strip()
    try:
        res = requests.post(url, json=body, timeout=timeout)
        if res.status_code != 200:
            return None
        return res.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def _squash(s):
    """Lowercase and drop spacing/punctuation so "Cubao - Divisoria" == "Cubao-Divisoria"."""
    return re.sub(r"[\W_]+", "", s.lower())


def phrasing_is_faithful(text, itinerary):
    """The rephrase must name every ride's route and mention transfers."""
    t = text.lower()
    st = _squash(text)
    if not all(_squash(l["route"]) in st for l in itinerary["legs"] if l["type"] != "Walk"):
        return False
    if itinerary["transfers"] > 0 and "lipat" not in t and "transfer" not in t:
        return False
    return True


def contains_fare_question(text):
    """True when the user is asking about fares/prices."""
    t = text.lower()
    return any(w in t for w in FARE_WORDS)
